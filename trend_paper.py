"""Hourly Donchian/EMA trend paper trader. Public prices only; no order API."""
import asyncio, csv, json, math, time, argparse, urllib.parse, urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import websockets

START=10_000.0
MAX_TOTAL_LEVERAGE=3.0
RISK_PER_TRADE=0.005
MAX_TOTAL_STOP_RISK=0.02
DEFAULT_TAKER_FEE_BPS=5.0
DEFAULT_SLIPPAGE_BPS=2.0
DEFAULT_SPREAD_BPS=2.0
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT"]

@dataclass
class Bar:
    ts:int; high:float; low:float; close:float
@dataclass
class Position:
    side:int; entry:float; qty:float; stop:float; entry_fee:float; take_profit:float=0.0

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":"local-paper/1.0"})
    with urllib.request.urlopen(req,timeout=15) as r:return json.loads(r.read())

def warmup(exchange,symbol):
    if exchange=="binance":
        rows=get_json(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=100")
        return [Bar(int(x[0]),float(x[2]),float(x[3]),float(x[4])) for x in rows if int(x[6])<int(time.time()*1000)]
    inst=symbol.replace("USDT","-USDT-SWAP")
    rows=get_json("https://www.okx.com/api/v5/market/history-candles?"+urllib.parse.urlencode({"instId":inst,"bar":"1H","limit":"100"}))["data"]
    return [Bar(int(x[0]),float(x[2]),float(x[3]),float(x[4])) for x in reversed(rows) if len(x)>8 and x[8]=="1"]

def ema(values,n):
    alpha=2/(n+1); out=values[0]
    for v in values[1:]:out=alpha*v+(1-alpha)*out
    return out
def atr(bars,n=20):
    trs=[]
    for i in range(1,len(bars)):
        b,prev=bars[i],bars[i-1]
        trs.append(max(b.high-b.low,abs(b.high-prev.close),abs(b.low-prev.close)))
    return sum(trs[-n:])/min(n,len(trs)) if trs else 0

class Engine:
    def __init__(self,exchange,state,fee_bps,slippage_bps,spread_bps,cooldown_hours):
        self.exchange=exchange; self.state=Path(state); self.cash=START; self.peak=START; self.halted=False
        self.fee_rate=fee_bps/10000; self.slippage_bps=slippage_bps; self.spread_bps=spread_bps; self.cooldown_ms=cooldown_hours*3600000; self.last_exit={}
        self.bars={s:warmup(exchange,s) for s in SYMBOLS}; self.pos={}; self.last_ts={s:(self.bars[s][-1].ts if self.bars[s] else 0) for s in SYMBOLS}
        if self.state.exists():
            d=json.loads(self.state.read_text()); self.cash=d.get("cash",START); self.peak=d.get("peak",START); self.halted=d.get("halted",False); self.pos={s:Position(**v) for s,v in d.get("positions",{}).items()}
        for f,h in [("trend_trades.csv","utc,symbol,action,side,price,qty,fee,pnl,total_equity,reason"),("trend_equity.csv","utc,total_equity,cash,unrealized,open_positions,halted")]:
            if not Path(f).exists():Path(f).write_text(h+"\n",encoding="utf-8")
        self.prices={s:(self.bars[s][-1].close if self.bars[s] else 0) for s in SYMBOLS}
    def floating(self):return sum(p.side*(self.prices.get(s,p.entry)-p.entry)*p.qty for s,p in self.pos.items())
    def equity(self):return self.cash+self.floating()
    def persist(self):self.state.write_text(json.dumps({"cash":self.cash,"peak":self.peak,"halted":self.halted,"positions":{s:asdict(p) for s,p in self.pos.items()}},indent=2))
    def fill(self,px,side):return px*(1+side*(self.slippage_bps+self.spread_bps/2)/10000)
    def log(self,s,action,p,px,fee,pnl,why):
        with open("trend_trades.csv","a",newline="",encoding="utf-8") as f:csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(),s,action,"LONG" if p.side>0 else "SHORT",px,p.qty,fee,pnl,round(self.equity(),2),why])
    def close(self,s,px,why):
        p=self.pos.pop(s); fill=self.fill(px,-p.side); pnl=p.side*(fill-p.entry)*p.qty; fee=fill*p.qty*self.fee_rate; self.last_exit[s]=self.last_ts[s]
        self.cash+=pnl-fee; self.prices[s]=px; self.log(s,"CLOSE",p,fill,fee,pnl,why)
    def on_bar(self,s,b):
        if b.ts<=self.last_ts[s]:return
        self.last_ts[s]=b.ts; bars=self.bars[s]; bars.append(b); bars[:]=bars[-120:]; self.prices[s]=b.close
        if len(bars)<55:return
        closes=[x.close for x in bars]; a=atr(bars); e20=ema(closes[-80:],20); e50=ema(closes[-100:],50)
        upper=max(x.high for x in bars[-21:-1]); lower=min(x.low for x in bars[-21:-1]); exit_low=min(x.low for x in bars[-11:-1]); exit_high=max(x.high for x in bars[-11:-1])
        signal=1 if b.close>upper and e20>e50 else (-1 if b.close<lower and e20<e50 else 0)
        p=self.pos.get(s)
        if p:
            if p.side>0:
                stop_hit=b.low<=p.stop; target_hit=b.high>=p.take_profit if p.take_profit else False
                px=p.stop if stop_hit else p.take_profit if target_hit else b.close
                if not stop_hit:p.stop=max(p.stop,b.close-3.0*a)
                channel_exit=b.close<exit_low
            else:
                stop_hit=b.high>=p.stop; target_hit=b.low<=p.take_profit if p.take_profit else False
                px=p.stop if stop_hit else p.take_profit if target_hit else b.close
                if not stop_hit:p.stop=min(p.stop,b.close+3.0*a)
                channel_exit=b.close>exit_high
            if stop_hit or target_hit or channel_exit or signal==-p.side:
                reason="stop (conservative same-bar priority)" if stop_hit else "2R take-profit" if target_hit else "10-bar exit/reversal"
                self.close(s,px,reason)
        elif signal and not self.halted and b.ts-self.last_exit.get(s,-self.cooldown_ms)>=self.cooldown_ms:
            stop_dist=min(max(3.0*a,b.close*.008),b.close*.08); total=self.equity(); risk_qty=total*RISK_PER_TRADE/stop_dist
            notional_used=sum(q*self.prices.get(k,v.entry) for k,v in self.pos.items()); remaining=max(0,total*MAX_TOTAL_LEVERAGE-notional_used)
            qty=min(risk_qty,remaining/b.close); risk_used=sum(v.qty*abs(self.prices.get(k,v.entry)-v.stop) for k,v in self.pos.items())
            if qty>0 and risk_used+qty*stop_dist<=total*MAX_TOTAL_STOP_RISK:
                entry=self.fill(b.close,signal); stop=entry-signal*stop_dist; target=entry+signal*2*stop_dist
                p=Position(signal,entry,qty,stop,0.0,target); fee=p.entry*qty*self.fee_rate; p.entry_fee=fee; self.cash-=fee; self.pos[s]=p; self.log(s,"OPEN",p,p.entry,fee,0,"20-bar breakout + EMA20/50; 3ATR stop; 2R target")
        total=self.equity(); self.peak=max(self.peak,total)
        if total<=self.peak*.90:self.halted=True
        with open("trend_equity.csv","a",newline="",encoding="utf-8") as f:csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(),round(total,2),round(self.cash,2),round(self.floating(),2),len(self.pos),self.halted])
        self.persist(); print(datetime.now(timezone.utc).isoformat(timespec="seconds"),s,"close",b.close,"ATR",round(a,6),"signal",signal,"cash",round(self.cash,2),"floating",round(self.floating(),2),"TOTAL",round(total,2),"halt",self.halted,flush=True)

async def run_binance(e):
    streams="/".join(s.lower()+"@kline_1h" for s in SYMBOLS); url="wss://fstream.binance.com/stream?streams="+streams
    while True:
        try:
            async with websockets.connect(url,ping_interval=150,ping_timeout=30) as ws:
                async for raw in ws:
                    d=json.loads(raw).get("data",{}); k=d.get("k",{})
                    if k.get("x"):e.on_bar(d["s"],Bar(int(k["t"]),float(k["h"]),float(k["l"]),float(k["c"])))
        except Exception as ex:print("Binance stream reconnect:",repr(ex),flush=True);await asyncio.sleep(5)
async def run_okx(e):
    args=[{"channel":"candle1H","instId":s.replace("USDT","-USDT-SWAP")} for s in SYMBOLS]
    while True:
        try:
            async with websockets.connect("wss://ws.okx.com/ws/v5/public",ping_interval=None) as ws:
                await ws.send(json.dumps({"op":"subscribe","args":args}))
                async def beat():
                    while True:await asyncio.sleep(20);await ws.send("ping")
                hb=asyncio.create_task(beat())
                try:
                    async for raw in ws:
                        if raw=="pong":continue
                        d=json.loads(raw); arg=d.get("arg",{}); rows=d.get("data",[])
                        if arg.get("channel")=="candle1H" and rows:
                            x=rows[0]
                            if len(x)>8 and x[8]=="1":e.on_bar(arg["instId"].replace("-USDT-SWAP","USDT"),Bar(int(x[0]),float(x[2]),float(x[3]),float(x[4])))
                finally:hb.cancel()
        except Exception as ex:print("OKX stream reconnect:",repr(ex),flush=True);await asyncio.sleep(5)
async def main():
    ap=argparse.ArgumentParser();ap.add_argument("--exchange",choices=["binance","okx"],default="okx");ap.add_argument("--days",type=int,default=60);ap.add_argument("--state",default="trend_state.json");ap.add_argument("--taker-fee-bps",type=float,default=DEFAULT_TAKER_FEE_BPS,help="fee per side in basis points; set from your account's current fee tier");ap.add_argument("--slippage-bps",type=float,default=DEFAULT_SLIPPAGE_BPS);ap.add_argument("--spread-bps",type=float,default=DEFAULT_SPREAD_BPS);ap.add_argument("--cooldown-hours",type=int,default=12);a=ap.parse_args()
    e=Engine(a.exchange,a.state,a.taker_fee_bps,a.slippage_bps,a.spread_bps,a.cooldown_hours);print(f"HOURLY DONCHIAN/EMA PAPER ONLY; no order API; USD 10000 start; account-wide 3x cap; fee={a.taker_fee_bps:g}bps/side; assumed spread={a.spread_bps:g}bps; slippage={a.slippage_bps:g}bps; cooldown={a.cooldown_hours}h")
    feed=asyncio.create_task(run_binance(e) if a.exchange=="binance" else run_okx(e))
    try:await asyncio.wait_for(feed,timeout=a.days*86400)
    except asyncio.TimeoutError:print("Observation period finished")
    except KeyboardInterrupt:feed.cancel();print("Stopped")
if __name__=="__main__":asyncio.run(main())


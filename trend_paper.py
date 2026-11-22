"""5-minute Donchian/EMA paper trader. Public prices only; no order API."""
import asyncio, csv, json, math, time, argparse, urllib.parse, urllib.request, urllib.error, subprocess, shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import websockets

START=10_000.0
MAX_TOTAL_LEVERAGE=3.0
BRACKET_PNL_FRACTION=0.10
DEFAULT_TAKER_FEE_BPS=5.0
DEFAULT_SLIPPAGE_BPS=2.0
DEFAULT_SPREAD_BPS=2.0
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT"]

@dataclass
class Bar:
    ts:int; open:float; high:float; low:float; close:float; volume:float
@dataclass
class Position:
    side:int; entry:float; qty:float; stop:float; entry_fee:float; take_profit:float=0.0

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":"local-paper/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=15) as r:return json.loads(r.read())
    except (urllib.error.URLError,TimeoutError) as py_error:
        # Some Windows Python/proxy combinations fail TLS while Windows PowerShell succeeds.
        ps=shutil.which("powershell.exe") or shutil.which("powershell")
        if not ps:raise py_error
        safe_url=url.replace("'","''")
        command="$ProgressPreference='SilentlyContinue'; Invoke-RestMethod -Uri '"+safe_url+"' | ConvertTo-Json -Depth 10 -Compress"
        try:
            out=subprocess.run([ps,"-NoLogo","-NoProfile","-NonInteractive","-Command",command],capture_output=True,text=True,timeout=25,check=True)
            return json.loads(out.stdout)
        except Exception as ps_error:
            raise RuntimeError(f"Python HTTPS failed ({py_error}); PowerShell fallback failed ({ps_error})") from ps_error

def warmup(exchange,symbol):
    if exchange=="binance":
        rows=get_json(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=5m&limit=100")
        return [Bar(int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])) for x in rows if int(x[6])<int(time.time()*1000)]
    inst=symbol.replace("USDT","-USDT-SWAP")
    rows=get_json("https://www.okx.com/api/v5/market/history-candles?"+urllib.parse.urlencode({"instId":inst,"bar":"5m","limit":"100"}))["data"]
    return [Bar(int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])) for x in reversed(rows) if len(x)>8 and x[8]=="1"]

def daily_streak(exchange,symbol):
    """Count consecutive completed up daily candles; never use the live daily candle."""
    now=int(time.time()*1000)
    if exchange=="binance":
        rows=get_json(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1d&limit=12")
        rows=[x for x in rows if int(x[0])+86_400_000<=now]
        closes=[float(x[4]) for x in rows]
    else:
        inst=symbol.replace("USDT","-USDT-SWAP")
        rows=get_json("https://www.okx.com/api/v5/market/history-candles?"+urllib.parse.urlencode({"instId":inst,"bar":"1Dutc","limit":"12"}))["data"]
        rows=[x for x in reversed(rows) if len(x)>8 and x[8]=="1" and int(x[0])+86_400_000<=now]
        closes=[float(x[4]) for x in rows]
    streak=0
    for i in range(len(closes)-1,0,-1):
        if closes[i]>closes[i-1]:streak+=1
        else:break
    return streak

def gainer_returns(exchange):
    """Rolling 24h returns for the configured watchlist, from public swap tickers."""
    if exchange=="binance":
        rows=get_json("https://fapi.binance.com/fapi/v1/ticker/24hr")
        return {s:float(x["priceChangePercent"])/100 for x in rows if (s:=x.get("symbol")) in SYMBOLS}
    rows=get_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP")["data"]
    wanted={s:s.replace("USDT","-USDT-SWAP") for s in SYMBOLS}; out={}
    for x in rows:
        sym=next((s for s,i in wanted.items() if x.get("instId")==i),None)
        if sym and float(x.get("open24h") or 0)>0:out[sym]=float(x["last"])/float(x["open24h"])-1
    return out

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
    def __init__(self,exchange,state,fee_bps,slippage_bps,spread_bps,cooldown_minutes):
        self.exchange=exchange; self.state=Path(state); self.cash=START; self.peak=START; self.halted=False
        self.fee_rate=fee_bps/10000; self.slippage_bps=slippage_bps; self.spread_bps=spread_bps; self.cooldown_ms=cooldown_minutes*60000; self.last_action_ts=0
        self.bars={s:warmup(exchange,s) for s in SYMBOLS}; self.pos={}; self.last_ts={s:(self.bars[s][-1].ts if self.bars[s] else 0) for s in SYMBOLS}
        self.daily_streaks={}; self.returns24={}; self.top_gainers=set(); self.context_updated=0
        if self.state.exists():
            d=json.loads(self.state.read_text()); self.cash=d.get("cash",START); self.peak=d.get("peak",START); self.halted=d.get("halted",False); self.last_action_ts=d.get("last_action_ts",0); self.pos={s:Position(**v) for s,v in d.get("positions",{}).items()}
        for f,h in [("paper_5m_trades.csv","utc,symbol,action,side,price,qty,fee,pnl,total_equity,reason"),("paper_5m_equity.csv","utc,total_equity,cash,unrealized,open_positions,halted")]:
            if not Path(f).exists():Path(f).write_text(h+"\n",encoding="utf-8")
        self.prices={s:(self.bars[s][-1].close if self.bars[s] else 0) for s in SYMBOLS}
    def refresh_market_context(self):
        """Refresh 24h watchlist ranking every call and daily streaks every 6h."""
        try:
            self.returns24=gainer_returns(self.exchange)
            ranked=sorted(((r,s) for s,r in self.returns24.items() if r>0),reverse=True)
            self.top_gainers={s for _,s in ranked[:3]}
        except Exception as ex:
            self.returns24={}; self.top_gainers=set()
            print("24h gainer context unavailable; gainer shorts disabled:",repr(ex),flush=True)
        if time.time()-self.context_updated>=6*3600:
            updated={}
            for s in SYMBOLS:
                try:updated[s]=daily_streak(self.exchange,s)
                except Exception as ex:print("daily streak unavailable",s,repr(ex),flush=True)
            self.daily_streaks=updated
            self.context_updated=time.time() if len(updated)==len(SYMBOLS) else time.time()-(6*3600-300)
        selected=sorted(self.top_gainers)
        print("Gainers(top3, watchlist):",", ".join(f"{s} {self.returns24[s]*100:+.2f}%/24h streak={self.daily_streaks.get(s,'?')}d" for s in selected) or "none",flush=True)
    def floating(self):return sum(p.side*(self.prices.get(s,p.entry)-p.entry)*p.qty for s,p in self.pos.items())
    def equity(self):return self.cash+self.floating()
    def persist(self):self.state.write_text(json.dumps({"cash":self.cash,"peak":self.peak,"halted":self.halted,"last_action_ts":self.last_action_ts,"positions":{s:asdict(p) for s,p in self.pos.items()}},indent=2))
    def fill(self,px,side):return px*(1+side*(self.slippage_bps+self.spread_bps/2)/10000)
    def log(self,s,action,p,px,fee,pnl,why):
        with open("paper_5m_trades.csv","a",newline="",encoding="utf-8") as f:csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(),s,action,"LONG" if p.side>0 else "SHORT",px,p.qty,fee,pnl,round(self.equity(),2),why])
    def close(self,s,px,why):
        p=self.pos.pop(s); fill=self.fill(px,-p.side); pnl=p.side*(fill-p.entry)*p.qty; fee=fill*p.qty*self.fee_rate; self.last_action_ts=self.last_ts[s]
        self.cash+=pnl-fee; self.prices[s]=px; self.log(s,"CLOSE",p,fill,fee,pnl,why)
    def on_bar(self,s,b):
        if b.ts<=self.last_ts[s]:return
        self.last_ts[s]=b.ts; bars=self.bars[s]; bars.append(b); bars[:]=bars[-120:]; self.prices[s]=b.close
        if len(bars)<55:return
        closes=[x.close for x in bars]; a=atr(bars); e20=ema(closes[-80:],20); e50=ema(closes[-100:],50)
        upper=max(x.high for x in bars[-21:-1]); lower=min(x.low for x in bars[-21:-1]); alpha_high=max(x.high for x in bars[-13:-1])
        avg_volume=sum(x.volume for x in bars[-21:-1])/20
        alpha_long=b.close>alpha_high and b.close>e20 and b.close>b.open and avg_volume>0 and b.volume>=1.5*avg_volume
        alpha_short=s in self.top_gainers and self.daily_streaks.get(s,0)>=3 and b.close<min(x.low for x in bars[-13:-1]) and b.close<e20 and b.close<b.open and avg_volume>0 and b.volume>=1.5*avg_volume
        trend_long=b.close>upper and e20>e50
        trend_short=b.close<lower and e20<e50
        signal=-1 if alpha_short else (1 if alpha_long or trend_long else (-1 if trend_short else 0))
        entry_reason="gainer short: top-3 watchlist 24h + >=3 completed up days + 5m bearish breakdown/volume" if alpha_short else "5m alpha impulse: 12-bar high + volume >=1.5x" if alpha_long else "20-bar breakout + EMA20/50" if trend_long else "20-bar bearish breakout + EMA20/50"
        p=self.pos.get(s)
        if p:
            if p.side>0:
                stop_hit=b.low<=p.stop; target_hit=b.high>=p.take_profit if p.take_profit else False
                px=p.stop if stop_hit else p.take_profit if target_hit else b.close
                channel_exit=False
            else:
                stop_hit=b.high>=p.stop; target_hit=b.low<=p.take_profit if p.take_profit else False
                px=p.stop if stop_hit else p.take_profit if target_hit else b.close
                channel_exit=False
            if stop_hit or target_hit:
                reason="10% principal stop (stop-first if both touched)" if stop_hit else "10% principal take-profit"
                self.close(s,px,reason)
        elif signal and not self.halted and not self.pos and b.ts-self.last_action_ts>=self.cooldown_ms:
            total=self.equity(); qty=total*MAX_TOTAL_LEVERAGE/b.close; entry=self.fill(b.close,signal)
            bracket_usd=START*BRACKET_PNL_FRACTION; price_gap=bracket_usd/qty
            stop=entry-signal*price_gap; target=entry+signal*price_gap
            p=Position(signal,entry,qty,stop,0.0,target); fee=p.entry*qty*self.fee_rate; p.entry_fee=fee; self.cash-=fee; self.pos[s]=p; self.last_action_ts=b.ts; self.log(s,"OPEN",p,p.entry,fee,0,entry_reason+"; +/-10% principal bracket; max 3x")
        total=self.equity(); self.peak=max(self.peak,total)
        if total<=self.peak*.90:self.halted=True
        with open("paper_5m_equity.csv","a",newline="",encoding="utf-8") as f:csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(),round(total,2),round(self.cash,2),round(self.floating(),2),len(self.pos),self.halted])
        self.persist(); print(datetime.now(timezone.utc).isoformat(timespec="seconds"),s,"close",b.close,"ATR",round(a,6),"signal",signal,"streak",self.daily_streaks.get(s,"?"),"gainer24h",round(self.returns24.get(s,0)*100,2),"cash",round(self.cash,2),"floating",round(self.floating(),2),"TOTAL",round(total,2),"halt",self.halted,flush=True)

async def run_binance(e):
    streams="/".join(s.lower()+"@kline_5m" for s in SYMBOLS); url="wss://fstream.binance.com/stream?streams="+streams
    while True:
        try:
            async with websockets.connect(url,ping_interval=150,ping_timeout=30) as ws:
                async for raw in ws:
                    d=json.loads(raw).get("data",{}); k=d.get("k",{})
                    if k.get("x"):e.on_bar(d["s"],Bar(int(k["t"]),float(k["o"]),float(k["h"]),float(k["l"]),float(k["c"]),float(k["v"])))
        except Exception as ex:print("Binance stream reconnect:",repr(ex),flush=True);await asyncio.sleep(5)
async def run_okx(e):
    args=[{"channel":"candle5m","instId":s.replace("USDT","-USDT-SWAP")} for s in SYMBOLS]
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
                        if arg.get("channel")=="candle5m" and rows:
                            x=rows[0]
                            if len(x)>8 and x[8]=="1":e.on_bar(arg["instId"].replace("-USDT-SWAP","USDT"),Bar(int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])))
                finally:hb.cancel()
        except Exception as ex:print("OKX stream reconnect:",repr(ex),flush=True);await asyncio.sleep(5)
async def refresh_context(e):
    while True:
        await asyncio.to_thread(e.refresh_market_context)
        await asyncio.sleep(300)
async def main():
    ap=argparse.ArgumentParser();ap.add_argument("--exchange",choices=["binance","okx"],default="okx");ap.add_argument("--days",type=int,default=60);ap.add_argument("--state",default="paper_5m_state.json");ap.add_argument("--taker-fee-bps",type=float,default=DEFAULT_TAKER_FEE_BPS,help="fee per side in basis points; set from your account's current fee tier");ap.add_argument("--slippage-bps",type=float,default=DEFAULT_SLIPPAGE_BPS);ap.add_argument("--spread-bps",type=float,default=DEFAULT_SPREAD_BPS);ap.add_argument("--cooldown-minutes",type=int,default=10);a=ap.parse_args()
    e=Engine(a.exchange,a.state,a.taker_fee_bps,a.slippage_bps,a.spread_bps,a.cooldown_minutes);print(f"5-MIN DONCHIAN/EMA PAPER ONLY; no order API; initial principal USD 10000; max 3x; per-trade stop/target USD {START*BRACKET_PNL_FRACTION:.0f}; 10-minute cooldown; fee={a.taker_fee_bps:g}bps/side")
    feed=asyncio.create_task(run_binance(e) if a.exchange=="binance" else run_okx(e)); context=asyncio.create_task(refresh_context(e))
    try:await asyncio.wait_for(feed,timeout=a.days*86400)
    except asyncio.TimeoutError:print("Observation period finished")
    except KeyboardInterrupt:feed.cancel();context.cancel();print("Stopped")
if __name__=="__main__":asyncio.run(main())


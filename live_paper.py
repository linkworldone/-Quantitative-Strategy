import asyncio,csv,json,math,time,argparse
from collections import deque
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from pathlib import Path
import websockets
START=10000.; MAXLEV=3.; RISK=.005; RISKCAP=.02; FEE=.0005
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT"]
@dataclass
class Pos:
 side:int; entry:float; qty:float; stop:float; reason:str
class Paper:
 def __init__(self,state):
  self.path=Path(state); self.cash=START; self.peak=START; self.halt=False; self.h={s:deque(maxlen=128) for s in SYMS}; self.pos={}
  if self.path.exists():
   try:
    d=json.loads(self.path.read_text()); self.cash=d["cash"]; self.peak=d["peak"]; self.halt=d["halt"]; self.pos={k:Pos(**v) for k,v in d["positions"].items()}
   except Exception as e: print("State load warning",e)
  for f,h in [("trades.csv","utc,symbol,action,side,price,qty,fee,pnl,equity,reason"),("equity.csv","utc,equity,positions,halted")]:
   if not Path(f).exists(): Path(f).write_text(h+"\n")
 def save(self):
  self.path.write_text(json.dumps({"cash":self.cash,"peak":self.peak,"halt":self.halt,"positions":{k:asdict(v) for k,v in self.pos.items()}},indent=2))
 def log(self,s,a,side,px,q,fee,pnl,why):
  with open("trades.csv","a",newline="") as f: csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(),s,a,side,px,q,fee,pnl,round(self.cash,2),why])
 async def tick(self,s,px):
  h=self.h[s]
  if h and abs(px/h[-1]-1)<1e-5:return
  h.append(px)
  if len(h)<32:return
  rr=[math.log(h[i]/h[i-1]) for i in range(len(h)-24,len(h))]; m=sum(rr)/len(rr); vol=math.sqrt(sum((x-m)**2 for x in rr)/(len(rr)-1))
  move=math.log(px/h[-25]); primes=(2,3,5,7,11,13,17,19,23,29,31); vals=[math.log(px/h[-p-1]) for p in primes]; pm=sum(vals)/len(vals); ps=math.sqrt(sum((v-pm)**2 for v in vals)/len(vals))+1e-12; pscr=pm/ps
  anomaly=abs(move)>max(2.5*vol*math.sqrt(24),.012)
  sig=1 if anomaly and move>0 and rr[-1]>.0015 else (-1 if move<0 and pscr<-.2 else 0)
  p=self.pos.get(s)
  if p:
   hit=px<=p.stop if p.side>0 else px>=p.stop
   if hit or sig==-p.side:self.close(s,px,"stop" if hit else "reversal")
  elif sig and not self.halt:self.open(s,px,sig,vol,"up anomaly" if sig>0 else "bearish prime")
  self.peak=max(self.peak,self.cash)
  if self.cash<=self.peak*.90:self.halt=True
  with open("equity.csv","a",newline="") as f: csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(),round(self.cash,2),len(self.pos),self.halt])
  self.save(); p=self.pos.get(s); side="LONG" if p and p.side>0 else "SHORT" if p else "FLAT"
  print(datetime.now(timezone.utc).isoformat(timespec="seconds"),s,format(px,".8g"),"vol24="+format(vol*100,".3f")+"%", "prime="+format(pscr,"+.2f"),"anomaly="+str(anomaly),side,"equity="+format(self.cash,".2f"),"halt="+str(self.halt))
 def open(self,s,px,side,vol,why):
  stop_pct=min(max(2.5*vol,.006),.04); qty=min(self.cash*RISK/(px*stop_pct),self.cash*MAXLEV/px)
  used=sum(p.qty*abs(p.entry-p.stop) for p in self.pos.values())
  if used+qty*px*stop_pct>self.cash*RISKCAP:return
  fee=qty*px*FEE; self.cash-=fee; self.pos[s]=Pos(side,px,qty,px*(1-stop_pct if side>0 else 1+stop_pct),why); self.log(s,"OPEN","LONG" if side>0 else "SHORT",px,qty,fee,0,why)
 def close(self,s,px,why):
  p=self.pos.pop(s); pnl=p.side*(px-p.entry)*p.qty; fee=px*p.qty*FEE; self.cash+=pnl-fee; self.log(s,"CLOSE","LONG" if p.side>0 else "SHORT",px,p.qty,fee,pnl,why)
async def binance(p):
 url="wss://fstream.binance.com/stream?streams="+"/".join(s.lower()+"@markPrice@1s" for s in SYMS)
 while True:
  try:
   async with websockets.connect(url,ping_interval=150,ping_timeout=30) as ws:
    async for raw in ws:
     d=json.loads(raw).get("data",{})
     if d.get("s") in p.h and d.get("p"): await p.tick(d["s"],float(d["p"]))
  except Exception as e: print("reconnect",e); await asyncio.sleep(3)
async def okx(p):
 args=[{"channel":"tickers","instId":s.replace("USDT","-USDT-SWAP")} for s in SYMS]
 while True:
  try:
   async with websockets.connect("wss://ws.okx.com/ws/v5/public",ping_interval=None) as ws:
    await ws.send(json.dumps({"op":"subscribe","args":args}))
    print("OKX WebSocket connected; waiting for ticker updates...", flush=True)
    async def beat():
     while True: await asyncio.sleep(20); await ws.send("ping")
    hb=asyncio.create_task(beat())
    try:
     async for raw in ws:
      if raw=="pong":continue
      d=json.loads(raw)
      # OKX sends subscribe acknowledgements and error events without a data array.
      if d.get("event") == "error":
       print("OKX subscription error:",d.get("msg",d),flush=True); continue
      if d.get("arg",{}).get("channel")=="tickers" and d.get("data"):
       t=d["data"][0]
       symbol=t.get("instId","").replace("-USDT-SWAP","USDT")
       if symbol in p.h and t.get("last"):
        await p.tick(symbol,float(t["last"]))
    finally: hb.cancel()
  except Exception as e: print("OKX feed disconnected; retrying in 5s:",repr(e),flush=True); await asyncio.sleep(5)
async def main():
 a=argparse.ArgumentParser(); a.add_argument("--exchange",choices=["binance","okx"],default="binance"); a.add_argument("--days",type=int,default=60); a.add_argument("--state",default="paper_state.json"); x=a.parse_args(); p=Paper(x.state)
 print("LOCAL PAPER ONLY | initial USD 10000 | leverage cap 3x | risk 0.5%/position | NO ORDER API")
 try: await asyncio.wait_for(binance(p) if x.exchange=="binance" else okx(p),timeout=x.days*86400)
 except asyncio.TimeoutError: print("Paper observation ended")
 except KeyboardInterrupt: print("Stopped")
if __name__=="__main__": asyncio.run(main())


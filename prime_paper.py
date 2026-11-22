"""
Prime-cycle perpetual futures paper research.
Public market data only. Never submits orders.
"""
import argparse, csv, json, math, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

PRIMES=(2,3,5,7,11,13,17,19,23,29,31)
def get(url):
    req=Request(url,headers={"User-Agent":"prime-cycle-paper/1.0"})
    with urlopen(req,timeout=20) as r: return json.loads(r.read())

def candles(exchange,symbol,interval,start_ms,end_ms):
    rows=[]
    if exchange=="binance":
        base="https://fapi.binance.com/fapi/v1/klines"
        while start_ms<end_ms:
            url=f"{base}?symbol={symbol}&interval={interval}&startTime={start_ms}&endTime={end_ms}&limit=1500"
            batch=get(url)
            if not batch: break
            rows.extend([[int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])] for x in batch])
            start_ms=batch[-1][0]+1
    else:
        base="https://www.okx.com/api/v5/market/history-candles"
        inst=symbol if symbol.endswith("-SWAP") else symbol.replace("USDT","-USDT")+"-SWAP"
        # OKX uses 'after' to page backward; gather recent data and filter range.
        before=end_ms
        while before>start_ms:
            batch=get(f"{base}?instId={inst}&bar={interval}&after={before}&limit=100")
            data=batch.get("data",[])
            if not data: break
            parsed=[[int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])] for x in data]
            rows.extend(parsed); before=min(x[0] for x in parsed)-1
            time.sleep(.12)
    return sorted({x[0]:x for x in rows if start_ms<=x[0]<=end_ms}.values())

def prime_feature(closes,lookback=31):
    # Compare log returns over prime-number bar horizons; centered rank score.
    out=[0.0]*len(closes)
    for i in range(lookback,len(closes)):
        vals=[]
        for p in PRIMES:
            vals.append(math.log(closes[i]/closes[i-p]))
        mean=sum(vals)/len(vals)
        # volatility scale keeps thresholds interpretable across assets
        scale=(sum((v-mean)**2 for v in vals)/len(vals))**.5
        out[i]=mean/(scale+1e-12)
    return out

def simulate(rows,fee=0.0005,threshold=0.35,initial=10000):
    closes=[r[4] for r in rows]
    scores=prime_feature(closes)
    cash=initial; pos=0; entry=0; trades=[]; peak=initial; maxdd=0
    # Signal is lagged one full candle; position changes at next candle close.
    for i in range(32,len(rows)-1):
        s=scores[i-1]
        target=1 if s>threshold else (-1 if s < -threshold else 0)
        px=closes[i]
        if target!=pos:
            if pos:
                cash*=1+pos*(px-entry)/entry
                cash*=1-fee
                trades.append({"time":rows[i][0],"side":"exit","price":px,"equity":cash})
            if target:
                cash*=1-fee; entry=px
                trades.append({"time":rows[i][0],"side":"long" if target>0 else "short","price":px,"equity":cash})
            pos=target
        equity=cash*(1+pos*(px-entry)/entry) if pos else cash
        peak=max(peak,equity); maxdd=min(maxdd,equity/peak-1)
    if pos:
        px=closes[-1]; cash*=1+pos*(px-entry)/entry; cash*=1-fee
    wins=sum(1 for a,b in zip(trades, trades[1:]) if a["side"] in ("long","short") and b["equity"]>a["equity"])
    return {"start_equity":initial,"end_equity":round(cash,2),"return_pct":round((cash/initial-1)*100,3),"max_drawdown_pct":round(maxdd*100,3),"signal_events":len(trades),"win_proxy":wins,"fee_per_side":fee,"threshold":threshold}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--exchange",choices=["binance","okx"],default="binance")
    p.add_argument("--symbol",default="BTCUSDT",help="Binance BTCUSDT; OKX BTC-USDT-SWAP")
    p.add_argument("--interval",default="1h")
    p.add_argument("--days",type=int,default=60)
    p.add_argument("--out",default="paper_report.json")
    a=p.parse_args()
    end=datetime.now(timezone.utc); start=end-timedelta(days=a.days)
    rows=candles(a.exchange,a.symbol,a.interval,int(start.timestamp()*1000),int(end.timestamp()*1000))
    if len(rows)<100: raise SystemExit(f"Insufficient candles: {len(rows)}")
    result={"exchange":a.exchange,"symbol":a.symbol,"interval":a.interval,"days_requested":a.days,"candles":len(rows),"period_utc":[datetime.fromtimestamp(rows[0][0]/1000,timezone.utc).isoformat(),datetime.fromtimestamp(rows[-1][0]/1000,timezone.utc).isoformat()],"model":"prime-horizon mean log-return / dispersion; one-bar lag; long/short/flat","metrics":simulate(rows),"note":"Research simulation only; excludes funding, slippage, liquidation and exchange-specific contract sizing."}
    with open(a.out,"w",encoding="utf-8") as f: json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
if __name__=="__main__": main()

"""Periodic timestamped collection of public market context; does not trade."""
import argparse, asyncio, json
from datetime import datetime,timezone
from context_feeds import binance_derivatives, fear_greed, news, coingecko_supply, ai_brief, onchain_provider_status

async def main():
 p=argparse.ArgumentParser()
 p.add_argument("--exchange",choices=["binance","okx"],default="binance")
 p.add_argument("--symbols",default="BTCUSDT,ETHUSDT")
 p.add_argument("--coins",default="bitcoin,ethereum",help="CoinGecko IDs aligned by order with symbols")
 a=p.parse_args(); symbols=[s.strip().upper() for s in a.symbols.split(",") if s.strip()]; coins=[s.strip() for s in a.coins.split(",")]
 while True:
  snapshot={"collected_utc":datetime.now(timezone.utc).isoformat(),"exchange":a.exchange,"assets":{}}
  fg=await asyncio.to_thread(fear_greed)
  for i,s in enumerate(symbols):
   deriv=await asyncio.to_thread(binance_derivatives,s) if a.exchange=="binance" else {"source":"OKX","data":{"available":False,"reason":"adapter pending"}}
   nw=await asyncio.to_thread(news,s)
   supply=await asyncio.to_thread(coingecko_supply,coins[i]) if i<len(coins) else {"data":{"available":False,"reason":"missing coin ID"}}
   ctx={"derivatives":deriv,"news":nw,"fear_greed":fg,"supply":supply,"onchain":onchain_provider_status()}
   ctx["ai_summary"]=await asyncio.to_thread(ai_brief,s,ctx)
   snapshot["assets"][s]=ctx
  with open("context.jsonl","a",encoding="utf-8") as f:f.write(json.dumps(snapshot,ensure_ascii=False)+"\n")
  print(snapshot["collected_utc"],"wrote context snapshot")
  await asyncio.sleep(300)
if __name__=="__main__":asyncio.run(main())

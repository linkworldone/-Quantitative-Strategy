"""Optional public context feeds. Missing/unconfigured inputs are explicitly null."""
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

def fetch(url, headers=None):
    req=urllib.request.Request(url,headers={"User-Agent":"quant-paper-research/1.0",**(headers or {})})
    with urllib.request.urlopen(req,timeout=12) as r:return json.loads(r.read())

def result(source,data,observed=None):
    return {"source":source,"observed_utc":observed or datetime.now(timezone.utc).isoformat(),"data":data}

def binance_derivatives(symbol):
    root="https://fapi.binance.com"
    try:
        premium=fetch(root+"/fapi/v1/premiumIndex?symbol="+symbol)
        oi=fetch(root+"/fapi/v1/openInterest?symbol="+symbol)
        book=fetch(root+"/fapi/v1/ticker/bookTicker?symbol="+symbol)
        pair=symbol.removesuffix("USDT")+"USDT"
        ratios=fetch(root+"/futures/data/topLongShortPositionRatio?symbol="+pair+"&period=5m&limit=1")
        return result("Binance USD-M public API",{"funding_rate":float(premium["lastFundingRate"]),"next_funding_ms":int(premium["nextFundingTime"]),"open_interest_contracts":float(oi["openInterest"]),"bid":float(book["bidPrice"]),"ask":float(book["askPrice"]),"top_trader_long_short":ratios[0] if ratios else None})
    except Exception as e:return result("Binance USD-M public API",{"error":str(e),"available":False})

def fear_greed():
    try:
        x=fetch("https://api.alternative.me/fng/?limit=1")
        d=x["data"][0]; return result("Alternative.me Fear & Greed",{"value":int(d["value"]),"classification":d["value_classification"],"timestamp":int(d["timestamp"])})
    except Exception as e:return result("Alternative.me Fear & Greed",{"error":str(e),"available":False})

def news(symbol):
    # GDELT public DOC API; headlines/snippets only, not full articles or verified sentiment.
    try:
        q=urllib.parse.quote('"'+symbol.replace("USDT","")+'" cryptocurrency')
        x=fetch("https://api.gdeltproject.org/api/v2/doc/doc?query="+q+"&mode=ArtList&format=json&sort=DateDesc&maxrecords=10")
        rows=[{"title":a.get("title"),"url":a.get("url"),"published":a.get("seendate"),"source":a.get("domain")} for a in x.get("articles",[])]
        return result("GDELT DOC public API",rows)
    except Exception as e:return result("GDELT DOC public API",{"error":str(e),"available":False})

def coingecko_supply(coin_id):
    key=os.getenv("COINGECKO_DEMO_API_KEY")
    if not key:return result("CoinGecko",{"available":False,"reason":"Set COINGECKO_DEMO_API_KEY; use canonical coin id"})
    try:
        x=fetch("https://api.coingecko.com/api/v3/coins/"+urllib.parse.quote(coin_id)+"?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false",{"x-cg-demo-api-key":key})
        m=x.get("market_data",{})
        return result("CoinGecko API",{"coin_id":coin_id,"circulating_supply":m.get("circulating_supply"),"total_supply":m.get("total_supply"),"max_supply":m.get("max_supply"),"market_cap_usd":m.get("market_cap",{}).get("usd")})
    except Exception as e:return result("CoinGecko API",{"available":False,"error":str(e)})

def ai_brief(symbol,context):
    key=os.getenv("OPENAI_API_KEY")
    if not key:return result("OpenAI Responses API",{"available":False,"reason":"Set OPENAI_API_KEY; AI is optional"})
    # AI summarizes sourced observations; never returns an order or changes risk limits.
    body=json.dumps({"model":os.getenv("OPENAI_MODEL","gpt-4.1-mini"),"input":[{"role":"system","content":"Summarize supplied crypto market/news context in Chinese. Separate facts from inference, cite supplied URLs, flag stale/missing/conflicting inputs. Do not give certainty or instructions to trade. Output concise JSON with summary, bullish_evidence, bearish_evidence, uncertainty."},{"role":"user","content":json.dumps({"symbol":symbol,"context":context},ensure_ascii=False)}]}).encode()
    try:
        req=urllib.request.Request("https://api.openai.com/v1/responses",data=body,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
        x=json.loads(urllib.request.urlopen(req,timeout=30).read())
        texts=[v.get("text","") for o in x.get("output",[]) for v in o.get("content",[]) if v.get("type")=="output_text"]
        return result("OpenAI Responses API",{"available":True,"text":"\n".join(texts)})
    except Exception as e:return result("OpenAI Responses API",{"available":False,"error":str(e)})

def onchain_provider_status():
    # General cross-chain whale transfer feeds are typically paid/keyed and need chain/token mappings.
    return result("On-chain provider",{"available":False,"reason":"No provider/API key and explicit chain-token mapping configured; do not infer whale direction from raw transfers"})

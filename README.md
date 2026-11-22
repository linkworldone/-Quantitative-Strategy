# Crypto perpetual paper research: live data adapters

Files:
- `live_paper.py`: local-only public Binance/OKX market-stream simulator.
- `context_feeds.py`: Binance derivatives, Alternative.me sentiment, GDELT news, optional CoinGecko supply and OpenAI summaries.
- `cost_model.py`: contract sizing and spread/slippage/funding/fee formulas.
- `context_daemon.py`: five-minute timestamped context snapshots in `context.jsonl`.

## Optional API configuration
No exchange trading keys are required or used. Set `COINGECKO_DEMO_API_KEY` for supply lookup and `OPENAI_API_KEY` for AI summarization; optionally set `OPENAI_MODEL`. Keep keys in local environment variables and never commit them. AI summarizes sourced evidence only and cannot create/override orders.

## Start
Python 3.10+:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python context_daemon.py --exchange binance --symbols BTCUSDT,ETHUSDT --coins bitcoin,ethereum
```
In a second terminal:
```powershell
python live_paper.py --exchange binance --days 60
```
Use exchange=okx for price paper feed. Context snapshots append every five minutes. Keep model settings fixed during the 60-day observation.

## Data integrity and important limit
Unavailable inputs are explicitly tagged, never silently treated as neutral. Binance top-trader ratio is a positioning proxy, not verified “smart money.” Fear & Greed is market-wide. GDELT provides article metadata/headlines, not verified full-text sentiment. Supply requires canonical CoinGecko IDs and API key. General cross-chain whale-flow requires a dedicated provider/key and correct chain/token mapping; until configured this input is unavailable.

**The live_paper execution loop is not yet wired to consume context_daemon snapshots or cost_model helpers.** Its fills/PnL remain simplified and do not fully account for funding, spread, depth/slippage, contract size, or liquidation mechanics. The adapters and formulas are available for integration, but this is not yet a cost-adjusted complete simulation. No real orders are sent. Do not treat results as validated or predictive.

Sources: [Binance USD-M Futures market data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data), [Alternative.me Fear & Greed](https://alternative.me/crypto/fear-and-greed-index/), [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses), [CoinGecko API](https://docs.coingecko.com/reference/coins-id).

# Crypto perpetual paper research

## Lower-turnover model

Use `trend_paper.py` for the hourly model. It uses confirmed 1-hour candles, a 20-bar Donchian breakout with EMA20/EMA50 trend confirmation, 20-bar ATR stop sizing, 10-bar channel exit, 12-hour re-entry cooldown, 0.5% equity risk per trade, 2% aggregate stop-risk ceiling, and a 3x account-wide notional cap.

Fee defaults are per side: taker 5 bps (0.05%), assumed spread 2 bps and slippage 2 bps. The simulator charges an adverse synthetic fill and fee on both entry and exit. These are conservative assumptions, not a promise of actual fills. Set the fee to the rate shown in your account. Do not set maker rates unless the order logic and fill model genuinely ensure maker execution.

Run for 60 days:
```powershell
python trend_paper.py --exchange okx --days 60 --taker-fee-bps 5
```
For Binance, use `--exchange binance` only where Binance's API is available. This environment received Binance HTTP 451 restricted-location responses, so Binance simulation could not be verified here. The script has no credentials and never sends orders. Trade/equity logs are `trend_trades.csv` and `trend_equity.csv`; state is `trend_state.json`.

Lower turnover comes from evaluating only closed hourly bars and waiting 12 hours after exit before re-entry. This reduces churn but can miss moves and does not guarantee higher net returns. Funding is not yet charged in this model, and spread is an estimate rather than live bid/ask execution. Review costs separately before using results.

## Existing experimental modules

- `live_paper.py`: earlier tick-sample prime heuristic; retained for comparison, not recommended as the primary evaluation.
- `context_feeds.py`: public derivatives, sentiment/news, optional CoinGecko supply/OpenAI summaries.
- `context_daemon.py`: five-minute context snapshots; these are not consumed by `trend_paper.py` signals.
- `cost_model.py`: reusable cost formula helpers.

The regular USDⓈ-M example fee in Binance's published fee explanation is maker 0.02%, taker 0.05%, while the actual fee varies by VIP level and discounts. OKX says rates depend on the account's tier and instrument; use the rate displayed for your own account. Sources: [Binance Futures fee explanation](https://www.binance.com/en/support/faq/detail/360033544231), [OKX fee rules](https://www.okx.com/help/trading-fee-rules-faq), [OKX account fee-rate API](https://www.okx.com/docs-v5/en/#rest-api-account-get-fee-rates).

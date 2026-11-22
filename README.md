# Crypto perpetual paper research

## 5-minute paper simulator

`trend_paper.py` consumes public 5-minute perpetual futures prices from OKX or Binance and never sends exchange orders. It uses a 10,000 USD virtual account, a 3x account-wide notional cap, estimated taker fees, spread and slippage, and a 10-minute cooldown. The per-position target and stop are each set to 10% of the initial account principal (1,000 USD gross PnL at the bracket), which is deliberately aggressive and suitable only for paper research.

Long entries include a 12-bar breakout with volume confirmation. The new gainer-short rule ranks the configured nine-symbol watchlist by rolling 24-hour return; it only considers the top three, requires at least three consecutive completed daily candles with higher closes, and waits for a 5-minute bearish breakdown with volume confirmation before opening a short. The gainer rank refreshes every five minutes and the daily streak is refreshed every six hours. This is a watchlist-relative ranking, not the exchange-wide gainers board.

Run for 60 days on OKX:

```powershell
python trend_paper.py --exchange okx --days 60
```

Run on Binance only where its public derivatives API is accessible:

```powershell
python trend_paper.py --exchange binance --days 60
```

Use `Ctrl+C` to stop. Trades are appended to `paper_5m_trades.csv`, equity snapshots to `paper_5m_equity.csv`, and account state is stored in `paper_5m_state.json`. To begin a fresh observation, stop the program and move or delete that state file and the two CSV files after saving any results you need.

Fees, spread and slippage are estimates; funding, contract-specific lot/face value, liquidation mechanics, and live order-book fill simulation are not yet modeled. Binance access previously returned HTTP 451 in the user's environment, while OKX REST and WebSocket have been used for local data tests. A 60-day simulation is a research sample, not evidence of future profitability.

## Earlier experimental modules

- `live_paper.py`: earlier tick-sample prime heuristic.
- `context_feeds.py` and `context_daemon.py`: supplemental public context prototypes; they are not consumed by the current strategy signals.
- `cost_model.py`: reusable cost formula helpers; not the active fill engine for `trend_paper.py`.


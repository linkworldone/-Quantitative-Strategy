# Prime-cycle perpetual futures paper research

A small, reproducible research scaffold for **crypto perpetual futures only**. The only model input is a prime-horizon price-return feature. This is an experimental hypothesis, not an edge claim or investment advice. It does not claim that prime numbers predict markets.

## Safety and scope
- Public candle endpoints only; no API key, account, order submission, leverage, or live-trading code.
- The backtest uses historical OHLCV, applies signals with a one-candle lag, and charges a configurable round-trip trading fee approximation.
- It does **not** model funding payments, realistic slippage, liquidation, market impact, or contract sizing. Treat results as preliminary.
- “Two months” means run the same frozen rules in a 60-day observation window. Do not tune parameters during the window. Compare the result with buy-and-hold and a no-signal baseline before drawing conclusions.

## Run a 60-day backtest
Python 3.10+; no third-party packages required:
```sh
python prime_paper.py --exchange binance --symbol BTCUSDT --interval 1h --days 60
```
For OKX perpetual swaps:
```sh
python prime_paper.py --exchange okx --symbol BTC-USDT-SWAP --interval 1H --days 60
```
The report is written to `paper_report.json`. Binance interval syntax follows its futures kline API; OKX uses bar values such as `1H`.

## Two-month paper protocol
1. Record a start date, exchange, contract, candle interval, fee setting and threshold. Keep these fixed for 60 days.
2. For a clean forward simulation, fetch candles once per hour and evaluate only after a candle closes; use the printed signal as a hypothetical position. This starter currently performs historical simulation; it does not run a persistent live paper loop or place demo orders.
3. Log timestamp, signal, hypothetical entry/exit, fees, and equity daily. Include funding and estimated slippage in a separate conservative ledger.
4. At day 60, assess net return, maximum drawdown, trade count, turnover and comparison baselines. Do not infer an edge from a single 60-day sample.

The Binance and OKX APIs used here are public market-data candle endpoints. Consult [Binance USDⓈ-M Futures API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data) and [OKX API v5](https://www.okx.com/docs-v5/en/#rest-api-market-data-get-candlesticks).

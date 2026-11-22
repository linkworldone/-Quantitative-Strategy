"""Transparent linear USDT-margined paper cost/PnL helpers."""
def qty_for_risk(equity, entry, stop_pct, risk_fraction=.005, max_leverage=3.0, contract_size=1.0):
    # contract_size is base units represented by one exchange contract; verify per instrument.
    if min(equity,entry,stop_pct,contract_size)<=0: raise ValueError("positive inputs required")
    units=min(equity*risk_fraction/(entry*stop_pct),equity*max_leverage/entry)
    return units/contract_size

def spread_bps(bid,ask):
    mid=(bid+ask)/2
    return (ask-bid)/mid*10000 if mid else 0.0

def estimated_fill(mid, side, spread_bps_value, slippage_bps):
    # side +1 buys (worse ask), -1 sells (worse bid)
    return mid*(1+side*(spread_bps_value/2+slippage_bps)/10000)

def funding_cashflow(notional, side, funding_rate):
    # Positive funding: longs pay shorts. Negative funding: shorts pay longs.
    return -side*notional*funding_rate

def realized_pnl(entry, exit, qty, side, contract_size=1.0, fee_rate=.0005, entry_cost_bps=0, exit_cost_bps=0, funding=0):
    units=qty*contract_size
    gross=side*(exit-entry)*units
    fees=(entry*units+exit*units)*fee_rate
    impact=(entry+exit)*units*(entry_cost_bps+exit_cost_bps)/10000
    return gross-fees-impact+funding

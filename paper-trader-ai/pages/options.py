from datetime import date

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from trader import services
from trader.config import CONTRACT_SIZE
from trader.options_math import analyze_strategy, payoff_at_expiry
from trader.portfolio import Order, OrderError
from trader.ui import money

pf = services.portfolio()
market = services.market()
st.title("Options lab")

STRATEGIES = {
    "covered_call": ("Covered call", "call", "sell_to_open"),
    "cash_secured_put": ("Cash-secured put", "put", "sell_to_open"),
    "long_call": ("Long call", "call", "buy_to_open"),
    "long_put": ("Long put", "put", "buy_to_open"),
}

c1, c2, c3 = st.columns([1, 1, 2])
symbol = c1.text_input("Underlying", value=st.session_state.get("symbol", "AAPL")).upper().strip()
st.session_state["symbol"] = symbol
strategy = c2.selectbox("Strategy", list(STRATEGIES), format_func=lambda s: STRATEGIES[s][0])
label, option_type, action = STRATEGIES[strategy]
try:
    spot = market.get_price(symbol)
    expirations = market.get_expirations(symbol)
except Exception as e:
    st.error(f"Couldn't load {symbol}: {e}")
    st.stop()
if not expirations:
    st.warning(f"{symbol} has no listed options.")
    st.stop()
today = date.today()
default_exp = next((i for i, e in enumerate(expirations) if (date.fromisoformat(e) - today).days >= 25), 0)
expiration = c3.selectbox("Expiration", expirations, index=default_exp,
                          format_func=lambda e: f"{e}  ({(date.fromisoformat(e) - today).days} DTE)")

if strategy == "covered_call":
    st.info(f"You own {pf.stock_qty(symbol)} {symbol} shares; {pf.free_shares(symbol)} are free to cover new calls.")
elif strategy == "cash_secured_put":
    st.info(f"Buying power available for collateral: {money(pf.buying_power())}")

with st.spinner("Loading chain..."):
    chain = market.chain_with_greeks(symbol, expiration, option_type, num_strikes=24)
st.caption(f"{symbol} @ {money(spot)} | {option_type.upper()}S expiring {expiration}")
st.dataframe(chain, hide_index=True, width="stretch", height=300,
             column_config={"prob_itm": st.column_config.ProgressColumn("Prob ITM", min_value=0, max_value=1, format="%.2f")})

# Default strike: ~0.30 delta for premium-selling strategies, at-the-money for long options.
target = 0.30 if action == "sell_to_open" else 0.5
default_idx = int((chain["delta"].abs() - target).abs().argmin())
c1, c2, c3 = st.columns(3)
strike = c1.selectbox("Strike", chain["strike"].tolist(), index=default_idx)
default_contracts = max(pf.free_shares(symbol) // CONTRACT_SIZE, 1) if strategy == "covered_call" else 1
contracts = c2.number_input("Contracts", min_value=1, value=int(default_contracts), step=1)
note = c3.text_input("Thesis / note (saved to journal)")

row = chain[chain["strike"] == strike].iloc[0]
side = "sell" if action == "sell_to_open" else "buy"
premium = row["bid"] if side == "sell" and row["bid"] > 0 else row["ask"] if row["ask"] > 0 else row["mid"]
m = analyze_strategy(strategy, spot, strike, premium, date.fromisoformat(expiration), row["iv"], int(contracts))

st.subheader(f"{label}: {contracts}x {symbol} {expiration} {strike:g} {option_type.upper()}")
k = st.columns(5)
k[0].metric("Premium", money(m["premium_total"]), f"{money(premium)}/sh at {'bid' if side == 'sell' else 'ask'}")
k[1].metric("Breakeven", money(m["breakeven"]))
k[2].metric("Max profit", m["max_profit"] if isinstance(m["max_profit"], str) else money(m["max_profit"]))
k[3].metric("Max loss", money(m["max_loss"]))
k[4].metric("Prob ITM", f"{m['prob_itm_at_expiry']:.0%}")
if strategy == "covered_call":
    st.caption(f"Static return {m['static_return_pct']}% ({m['annualized_static_return_pct']}% annualized) | "
               f"if called {m['if_called_return_pct']}% | downside cushion {m['downside_protection_pct']}%")
elif strategy == "cash_secured_put":
    st.caption(f"Return on collateral {m['return_on_collateral_pct']}% ({m['annualized_return_pct']}% annualized) | "
               f"collateral {money(m['capital_required'])} | effective buy price {money(m['effective_purchase_price'])}")
st.caption(f"Theta {money(m['theta_per_day_total'])}/day | delta per contract {m['delta_per_contract']} | IV {m['implied_vol']:.1%}")

prices = np.linspace(spot * 0.75, spot * 1.25, 200)
pnl = payoff_at_expiry(strategy, prices, spot, strike, premium, int(contracts))
fig = go.Figure()
fig.add_trace(go.Scatter(x=prices, y=np.where(pnl >= 0, pnl, np.nan), fill="tozeroy", name="Profit", line=dict(color="#2e7d32")))
fig.add_trace(go.Scatter(x=prices, y=np.where(pnl < 0, pnl, np.nan), fill="tozeroy", name="Loss", line=dict(color="#c62828")))
fig.add_vline(x=spot, line_dash="dot", annotation_text="spot")
fig.add_vline(x=m["breakeven"], line_dash="dash", annotation_text="breakeven")
fig.update_layout(title="P&L at expiration", xaxis_title=f"{symbol} price", yaxis_title="P&L ($)", height=360,
                  margin=dict(t=40, b=10), showlegend=False)
st.plotly_chart(fig, width="stretch")

order = Order("option", action, symbol, int(contracts), option_type, float(strike), expiration, note=note or None)
try:
    pv = pf.preview(order)
    st.caption(f"Estimated cash impact {money(pv.cash_delta)} including {money(pv.fees)} commission")
    can_place = True
except OrderError as e:
    st.warning(str(e))
    can_place = False
if st.button(f"Place: {order.describe()}", type="primary", disabled=not can_place):
    try:
        fill = pf.execute(order)
        services.reindex_journal(pf)
        st.success(f"Filled at {money(fill.price)} per share ({money(fill.cash_delta)} cash)")
    except OrderError as e:
        st.error(str(e))

st.divider()
st.subheader("Open option positions")
positions = pf.options()
if not positions:
    st.caption("None yet.")
for p in positions:
    close_action = "buy_to_close" if p["qty"] < 0 else "sell_to_close"
    close = Order("option", close_action, p["symbol"], abs(p["qty"]), p["option_type"], p["strike"], p["expiration"])
    with st.container(border=True):
        a, b = st.columns([5, 1])
        strat = pf.position_strategy(p["option_type"], p["qty"]).replace("_", " ")
        a.markdown(f"**{p['qty']:+d}x {p['symbol']} {p['expiration']} {p['strike']:g} {p['option_type'].upper()}** "
                   f"({strat}) opened at {money(p['avg_price'])}")
        try:
            pv = pf.preview(close)
        except Exception as e:  # no quote, market data hiccup, etc.
            a.caption(f"Can't close right now: {e}")
            continue
        pnl_close = (pv.price - p["avg_price"]) * CONTRACT_SIZE * p["qty"] - pv.fees
        a.caption(f"Close now at {money(pv.price)} -> P&L {money(pnl_close)}")
        if b.button("Close", key=f"close-{p['id']}"):
            fill = pf.execute(close)
            services.reindex_journal(pf)
            st.toast(f"Closed for realized {money(fill.realized_pnl)}")
            st.rerun()

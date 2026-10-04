import plotly.graph_objects as go
import streamlit as st

from trader import services
from trader.portfolio import Order, OrderError
from trader.ui import money

pf = services.portfolio()
market = services.market()
st.title("Trade stocks")

symbol = st.text_input("Symbol", value=st.session_state.get("symbol", "AAPL")).upper().strip()
st.session_state["symbol"] = symbol
if not symbol:
    st.stop()

try:
    q = market.get_quote(symbol)
except Exception as e:
    st.error(f"Couldn't load {symbol}: {e}")
    st.stop()

c = st.columns(5)
c[0].metric(symbol, money(q["price"]), f"{q['change_pct']:+.2f}%" if q["change_pct"] is not None else None)
c[1].metric("52w high", money(q["year_high"]))
c[2].metric("52w low", money(q["year_low"]))
c[3].metric("30d realized vol", f"{q['realized_vol_30d']:.1%}")
c[4].metric("You own", f"{pf.stock_qty(symbol)} sh", help=f"{pf.free_shares(symbol)} not covering calls")

period = st.segmented_control("Range", ["1mo", "3mo", "6mo", "1y", "5y"], default="6mo")
h = market.get_history(symbol, period or "6mo")
fig = go.Figure(go.Candlestick(x=h.index, open=h["Open"], high=h["High"], low=h["Low"], close=h["Close"]))
fig.update_layout(height=380, xaxis_rangeslider_visible=False, margin=dict(t=10, b=10))
st.plotly_chart(fig, width="stretch")

st.subheader("Place a market order")
c1, c2, c3 = st.columns(3)
side = c1.radio("Side", ["buy", "sell"], horizontal=True)
qty = c2.number_input("Shares", min_value=1, value=10, step=1)
note = c3.text_input("Thesis / note (saved to journal)")
order = Order("stock", side, symbol, int(qty), note=note or None)
try:
    pv = pf.preview(order)
    st.caption(f"Estimated fill {money(pv.price)} x {qty} = {money(abs(pv.cash_delta))}. "
               f"Buying power after: {money(pf.buying_power() + pv.cash_delta)}")
    can_place = True
except OrderError as e:
    st.warning(str(e))
    can_place = False

if st.button(f"{side.title()} {qty} {symbol}", type="primary", disabled=not can_place):
    try:
        fill = pf.execute(order)
        services.reindex_journal(pf)
        st.success(f"Filled: {order.describe()} at {money(fill.price)}"
                   + (f" | realized P&L {money(fill.realized_pnl)}" if fill.realized_pnl else ""))
    except OrderError as e:
        st.error(str(e))

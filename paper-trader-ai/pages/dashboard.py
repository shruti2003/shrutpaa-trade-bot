import pandas as pd
import plotly.express as px
import streamlit as st

from trader import services
from trader.ui import money, render_pending_orders, trades_frame

pf = services.portfolio()
st.title("Portfolio dashboard")

with st.spinner("Marking positions to market..."):
    snap = pf.snapshot()
pf.record_equity_snapshot(snap["equity"], snap["cash"])

c = st.columns(5)
c[0].metric("Equity", money(snap["equity"]), f"{money(snap['total_pnl'])} ({snap['total_return_pct']:+.2f}%)")
c[1].metric("Cash", money(snap["cash"]))
c[2].metric("Buying power", money(snap["buying_power"]),
            help=f"{money(snap['put_collateral_reserved'])} reserved for cash-secured puts")
c[3].metric("Realized P&L", money(snap["realized_pnl"]), help="Includes commissions")
c[4].metric("Net delta", f"{snap['net_delta_shares']:,.0f} sh", help="Equivalent share exposure across stocks and options")

render_pending_orders(pf, "dash")

left, right = st.columns([2, 1])
with left:
    hist = pd.DataFrame(pf.equity_history())
    if len(hist) > 1:
        st.plotly_chart(px.line(hist, x="date", y="equity", title="Equity (daily snapshot)", markers=True),
                        width="stretch")
    else:
        st.info("The equity curve fills in as you come back on different days.")
with right:
    alloc = [{"asset": "Cash (free)", "value": snap["buying_power"]},
             {"asset": "Put collateral", "value": snap["put_collateral_reserved"]}]
    alloc += [{"asset": s["symbol"], "value": s["market_value"]} for s in snap["stocks"]]
    alloc = [a for a in alloc if a["value"] > 0]
    st.plotly_chart(px.pie(pd.DataFrame(alloc), names="asset", values="value", hole=0.5, title="Allocation"),
                    width="stretch")

st.subheader("Stocks")
if snap["stocks"]:
    st.dataframe(pd.DataFrame(snap["stocks"])[
        ["symbol", "qty", "avg_cost", "price", "market_value", "unrealized_pnl", "unrealized_pct", "covered_by_calls"]],
        hide_index=True, width="stretch")
else:
    st.caption("No stock positions yet. Head to Trade Stocks.")

st.subheader("Options")
if snap["options"]:
    st.dataframe(pd.DataFrame(snap["options"])[
        ["symbol", "strategy", "option_type", "strike", "expiration", "dte", "qty", "avg_price", "mark",
         "underlying_price", "unrealized_pnl", "delta", "theta_per_day", "prob_itm", "iv"]],
        hide_index=True, width="stretch",
        column_config={"prob_itm": st.column_config.ProgressColumn("Prob ITM", min_value=0, max_value=1, format="%.2f")})
    theta = sum(o["theta_per_day"] for o in snap["options"])
    st.caption(f"Portfolio theta: {money(theta)}/day (positive = you earn time decay)")
else:
    st.caption("No option positions. Try a covered call or cash-secured put in the Options Lab.")

st.subheader("Recent trades")
df = trades_frame(pf.trades(limit=10))
if not df.empty:
    st.dataframe(df, hide_index=True, width="stretch")

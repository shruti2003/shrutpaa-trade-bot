import pandas as pd
import plotly.express as px
import streamlit as st

from trader import services
from trader.ui import money, trades_frame

pf = services.portfolio()
st.title("Journal & trade history")
st.caption("Everything here is indexed into the RAG knowledge base, so the AI copilot can answer questions about "
           "your own trading history.")

trades = pf.trades()
with st.form("note", clear_on_submit=True):
    st.markdown("**New journal entry**")
    text = st.text_area("What's your thesis, plan, or lesson learned?")
    c1, c2 = st.columns(2)
    symbol = c1.text_input("Ticker (optional)")
    options = [None] + [t["id"] for t in trades[:50]]
    labels = {t["id"]: f"#{t['id']} {t['ts'][:10]} {t['action']} {t['qty']} {t['symbol']}" for t in trades[:50]}
    trade_id = c2.selectbox("Link to trade (optional)", options, format_func=lambda i: "None" if i is None else labels[i])
    if st.form_submit_button("Save", type="primary") and text.strip():
        linked_symbol = symbol or next((t["symbol"] for t in trades if t["id"] == trade_id), None)
        pf.add_journal(text.strip(), linked_symbol, trade_id)
        services.reindex_journal(pf)
        st.toast("Saved and indexed")

entries = pf.journal()
if entries:
    st.subheader("Entries")
    for j in entries[:30]:
        tag = " | ".join(x for x in [j["ts"][:10], j["symbol"], f"trade #{j['trade_id']}" if j["trade_id"] else None] if x)
        st.markdown(f"<small>{tag}</small><br>{j['text']}", unsafe_allow_html=True)
        st.divider()

st.subheader("Trade history")
df = trades_frame(trades)
if df.empty:
    st.caption("No trades yet.")
    st.stop()
c = st.columns(3)
closing = df[~df["action"].isin(["buy", "buy_to_open", "sell_to_open"])]
wins = (closing["realized_pnl"] > 0).sum()
c[0].metric("Trades", len(df))
c[1].metric("Realized P&L", money(df["realized_pnl"].sum()))
c[2].metric("Win rate (closing trades)", f"{wins / len(closing):.0%}" if len(closing) else "n/a")

by_strategy = df.assign(strategy=df["strategy"].fillna("stock")).groupby("strategy", as_index=False)["realized_pnl"].sum()
st.plotly_chart(px.bar(by_strategy, x="strategy", y="realized_pnl", title="Realized P&L by strategy",
                       color="realized_pnl", color_continuous_scale="RdYlGn"), width="stretch")
st.dataframe(df, hide_index=True, width="stretch")
st.download_button("Download CSV", df.to_csv(index=False), "trades.csv", "text/csv")

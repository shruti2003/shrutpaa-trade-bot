import streamlit as st

from trader import db, services
from trader.config import STARTING_CASH
from trader.ui import money

st.set_page_config(page_title="Paper Trader AI", page_icon=":material/candlestick_chart:", layout="wide")
st.html("""<style>
[data-testid="stMetricValue"] { font-size: 1.35rem; }
[data-testid="stMetricLabel"] p { font-size: 0.8rem; }
[data-testid="stMetricDelta"] { font-size: 0.8rem; }
</style>""")

nav = st.navigation([
    st.Page("pages/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True),
    st.Page("pages/stocks.py", title="Trade Stocks", icon=":material/show_chart:"),
    st.Page("pages/options.py", title="Options Lab", icon=":material/stacked_line_chart:"),
    st.Page("pages/assistant.py", title="AI Copilot", icon=":material/smart_toy:"),
    st.Page("pages/journal.py", title="Journal & History", icon=":material/menu_book:"),
    st.Page("pages/knowledge.py", title="Knowledge Base (RAG)", icon=":material/database:"),
])

pf = services.portfolio()
with st.sidebar:
    st.markdown("### Paper account")
    st.metric("Cash", money(pf.cash()))
    st.metric("Buying power", money(pf.buying_power()),
              help="Cash minus collateral reserved for cash-secured puts.")
    st.caption("Simulated money with 15-min delayed Yahoo Finance data. Not financial advice.")
    with st.expander("Reset account"):
        start = st.number_input("Starting cash", min_value=1_000.0, value=STARTING_CASH, step=1_000.0)
        confirm = st.checkbox("Delete all trades, positions and journal entries")
        if st.button("Reset", disabled=not confirm, type="primary"):
            db.reset(pf.conn, start)
            services.reindex_journal(pf)
            st.session_state.clear()
            st.rerun()

for event in st.session_state.pop("expiration_events", []):
    st.toast(event, icon=":material/event:")

nav.run()

import pandas as pd
import streamlit as st

from trader import ingest, services
from trader.rag import SOURCES

pf = services.portfolio()
kb = services.kb()
market = services.market()
st.title("Knowledge base (RAG)")
st.caption("Chunks are embedded locally (all-MiniLM-L6-v2) into ChromaDB and retrieved by the AI copilot with "
           "metadata filters by source and ticker.")

stats = kb.stats()
cols = st.columns(len(SOURCES))
for col, s in zip(cols, SOURCES):
    col.metric(f"{s} chunks", stats.get(s, 0))

c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("**Research a ticker**")
    symbol = st.text_input("Ticker", value=st.session_state.get("symbol", "AAPL")).upper().strip()
    news = st.checkbox("Latest news headlines", value=True)
    form = st.selectbox("SEC filing", ["None", "10-K", "10-Q"])
    if st.button("Fetch & index", type="primary"):
        with st.spinner("Fetching and embedding..."):
            try:
                if news:
                    st.write(f"News: {ingest.ingest_news(kb, market, symbol)} chunks")
                if form != "None":
                    st.write(f"{form}: {ingest.ingest_filing(kb, symbol, form)} chunks")
            except Exception as e:
                st.error(f"Ingest failed: {e}")
with c2, st.container(border=True):
    st.markdown("**Maintain**")
    if st.button("Re-index strategy guides"):
        st.write(f"{ingest.ingest_strategy_docs(kb)} chunks")
    if st.button("Re-index journal & trades"):
        st.write(f"{ingest.ingest_journal(kb, pf)} chunks")
    upload = st.file_uploader("Add your own notes or guides (.md / .txt)", type=["md", "txt"])
    if upload and st.button("Index upload"):
        n = kb.add_document(upload.read().decode("utf-8", "ignore"), "strategy", f"upload:{upload.name}",
                            title=upload.name)
        st.write(f"{n} chunks")

st.subheader("Search playground")
q = st.text_input("Query", "When should I roll a covered call?")
c1, c2, c3 = st.columns([2, 1, 1])
srcs = c1.multiselect("Sources", SOURCES, default=list(SOURCES))
sym = c2.text_input("Ticker filter").upper().strip() or None
k = c3.slider("Top k", 1, 15, 5)
if q:
    hits = kb.search(q, k=k, sources=srcs or None, symbol=sym)
    if not hits:
        st.caption("No results.")
    for h in hits:
        with st.expander(f"{h.score:.2f}  {h.citation()}"):
            st.write(h.text)
            if h.url:
                st.markdown(f"[source]({h.url})")

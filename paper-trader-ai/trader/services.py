"""Shared, cached app resources for Streamlit pages."""
import streamlit as st

from . import ingest
from .config import CHROMA_DIR, DB_PATH, STARTING_CASH
from .db import connect
from .market import YahooMarket
from .portfolio import Portfolio
from .rag import KnowledgeBase


@st.cache_resource
def _conn():
    return connect(DB_PATH, STARTING_CASH)


@st.cache_resource
def market() -> YahooMarket:
    return YahooMarket()


@st.cache_resource
def kb() -> KnowledgeBase:
    base = KnowledgeBase(CHROMA_DIR)
    if base.stats()["strategy"] == 0:
        ingest.ingest_strategy_docs(base)
    return base


def portfolio() -> Portfolio:
    pf = Portfolio(_conn(), market())
    # Settle expired options once per browser session.
    if not st.session_state.get("_expirations_processed"):
        st.session_state["_expirations_processed"] = True
        events = pf.process_expirations()
        if events:
            ingest.ingest_journal(kb(), pf)
            st.session_state["expiration_events"] = events
    return pf


def reindex_journal(pf: Portfolio) -> None:
    ingest.ingest_journal(kb(), pf)

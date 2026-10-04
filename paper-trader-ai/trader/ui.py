"""Reusable Streamlit widgets."""
import pandas as pd
import streamlit as st

from .portfolio import OrderError, Portfolio
from .services import reindex_journal


def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def render_pending_orders(pf: Portfolio, key_prefix: str) -> None:
    pending = pf.pending()
    if not pending:
        return
    st.subheader(f"AI-proposed orders awaiting approval ({len(pending)})")
    for p in pending:
        order = p["order"]
        with st.container(border=True):
            c1, c2, c3 = st.columns([6, 1, 1])
            c1.markdown(f"**{order.describe()}**  \n{p['rationale'] or ''}")
            try:
                pv = pf.preview(order)
                c1.caption(f"Est. fill {money(pv.price)} | cash impact {money(pv.cash_delta)} | fees {money(pv.fees)}")
            except OrderError as e:
                c1.warning(f"Can't execute right now: {e}")
            except Exception as e:
                c1.caption(f"Quote unavailable: {e}")
            if c2.button("Approve", key=f"{key_prefix}-ok-{p['id']}", type="primary"):
                try:
                    fill = pf.resolve_pending(p["id"], approve=True)
                    reindex_journal(pf)
                    st.toast(f"Executed {order.describe()} at {money(fill.price)}")
                except OrderError as e:
                    st.error(str(e))
                st.rerun()
            if c3.button("Reject", key=f"{key_prefix}-no-{p['id']}"):
                pf.resolve_pending(p["id"], approve=False)
                st.rerun()


def trades_frame(trades: list[dict]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert(None).dt.strftime("%Y-%m-%d %H:%M")
    cols = ["id", "ts", "symbol", "asset_type", "action", "qty", "price", "option_type", "strike", "expiration",
            "strategy", "fees", "cash_delta", "realized_pnl", "note"]
    return df[cols]

"""Loaders that turn strategy docs, your journal, news, and SEC filings into RAG documents."""
import re
from functools import lru_cache
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .config import KNOWLEDGE_DIR, SEC_USER_AGENT
from .portfolio import Portfolio
from .rag import KnowledgeBase


def ingest_strategy_docs(kb: KnowledgeBase, directory: Path = KNOWLEDGE_DIR) -> int:
    """Index each '## ' section of every markdown file as its own document."""
    total = 0
    kb.delete(source="strategy")
    for path in sorted(directory.glob("*.md")):
        text = path.read_text()
        doc_title = (re.search(r"^# (.+)$", text, re.M) or [None, path.stem])[1]
        for section in re.split(r"(?m)^## ", text)[1:]:
            heading, _, body = section.partition("\n")
            total += kb.add_document(body, source="strategy", key=f"{path.stem}:{heading}",
                                     title=f"{doc_title} - {heading.strip()}")
    return total


def _trade_sentence(t: dict) -> str:
    when = t["ts"][:10]
    if t["asset_type"] == "stock":
        what = f"{t['action']} {t['qty']} shares of {t['symbol']} at ${t['price']:.2f}"
    else:
        what = (f"{t['action'].replace('_', ' ')} {t['qty']} {t['symbol']} {t['expiration']} "
                f"${t['strike']:g} {t['option_type']} contract(s) at ${t['price']:.2f} premium")
        if t["strategy"]:
            what += f" ({t['strategy'].replace('_', ' ')})"
    s = f"On {when}: {what}. Cash impact ${t['cash_delta']:,.2f}."
    if t["realized_pnl"]:
        s += f" Realized P&L ${t['realized_pnl']:,.2f}."
    if t["note"]:
        s += f" Note: {t['note']}"
    return s


def ingest_journal(kb: KnowledgeBase, portfolio: Portfolio) -> int:
    """Rebuild the journal index: one document per trade (with any linked notes) plus standalone notes."""
    kb.delete(source="journal")
    notes_by_trade: dict[int, list[str]] = {}
    standalone = []
    for j in portfolio.journal():
        if j["trade_id"]:
            notes_by_trade.setdefault(j["trade_id"], []).append(j["text"])
        else:
            standalone.append(j)
    total = 0
    for t in portfolio.trades():
        text = _trade_sentence(t)
        for note in notes_by_trade.get(t["id"], []):
            text += f"\n\nJournal: {note}"
        total += kb.add_document(text, source="journal", key=f"trade:{t['id']}", symbol=t["symbol"],
                                 title=f"Trade #{t['id']} {t['symbol']}", date=t["ts"][:10])
    for j in standalone:
        total += kb.add_document(j["text"], source="journal", key=f"note:{j['id']}", symbol=j["symbol"],
                                 title=f"Journal note #{j['id']}" + (f" {j['symbol']}" if j["symbol"] else ""),
                                 date=j["ts"][:10])
    return total


def ingest_news(kb: KnowledgeBase, market, symbol: str) -> int:
    symbol = symbol.upper()
    kb.delete(source="news", symbol=symbol)
    total = 0
    for item in market.get_news(symbol):
        summary = BeautifulSoup(item["summary"], "html.parser").get_text(" ", strip=True)
        total += kb.add_document(f"{item['title']}. {summary}", source="news", key=f"{symbol}:{item['url']}",
                                 title=item["title"], symbol=symbol, url=item["url"], date=item["published"][:16])
    return total


# ---------- SEC EDGAR ----------

def _sec_get(url: str) -> requests.Response:
    resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp


@lru_cache(maxsize=1)
def _ticker_to_cik() -> dict[str, int]:
    data = _sec_get("https://www.sec.gov/files/company_tickers.json").json()
    return {row["ticker"]: row["cik_str"] for row in data.values()}


# (section name, start pattern, end pattern) - the longest match wins so we skip the table of contents.
_SECTIONS = {
    "10-K": [("Risk Factors", r"item\s*1a\.?\s*risk\s*factors", r"item\s*1b\.?|item\s*2\.?\s*properties"),
             ("MD&A", r"item\s*7\.?\s*management", r"item\s*7a\.?|item\s*8\.?\s*financial")],
    "10-Q": [("MD&A", r"item\s*2\.?\s*management", r"item\s*3\.?|item\s*4\.?"),
             ("Risk Factors", r"item\s*1a\.?\s*risk\s*factors", r"item\s*2\.?\s*unregistered|item\s*5\.?|item\s*6\.?")],
}


def _extract_section(text: str, start: str, end: str) -> str:
    best = ""
    for m in re.finditer(start, text, re.I):
        e = re.search(end, text[m.end():], re.I)
        candidate = text[m.start(): m.end() + (e.start() if e else 60_000)]
        if len(candidate) > len(best):
            best = candidate
    return best


def latest_filing(symbol: str, form: str = "10-K") -> dict:
    cik = _ticker_to_cik().get(symbol.upper())
    if cik is None:
        raise ValueError(f"No SEC CIK found for {symbol}")
    recent = _sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
    for i, f in enumerate(recent["form"]):
        if f == form:
            acc = recent["accessionNumber"][i].replace("-", "")
            return {"cik": cik, "form": form, "date": recent["filingDate"][i],
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{recent['primaryDocument'][i]}"}
    raise ValueError(f"No {form} filings found for {symbol}")


def ingest_filing(kb: KnowledgeBase, symbol: str, form: str = "10-K", max_chars_per_section: int = 120_000) -> int:
    symbol = symbol.upper()
    meta = latest_filing(symbol, form)
    html = _sec_get(meta["url"]).text
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", text))
    total = 0
    for name, start, end in _SECTIONS[form]:
        section = _extract_section(text, start, end)[:max_chars_per_section]
        if section:
            total += kb.add_document(section, source="filing", key=f"{symbol}:{form}:{name}", symbol=symbol,
                                     title=f"{symbol} {form} ({meta['date']}) - {name}", url=meta["url"],
                                     date=meta["date"], max_chars=1500)
    return total

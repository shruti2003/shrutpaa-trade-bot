"""Market data from Yahoo Finance (via yfinance), with a small TTL cache.

Quotes are delayed ~15 minutes, which is fine for paper trading.
"""
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from .options_math import bs_price, greeks, implied_vol, year_fraction


@dataclass
class OptionQuote:
    bid: float
    ask: float
    last: float
    iv: float
    open_interest: int = 0
    volume: int = 0

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last

    def fill_price(self, side: str) -> float:
        """Market orders buy at the ask and sell at the bid; fall back to mid/last when the book is empty."""
        price = self.ask if side == "buy" else self.bid
        return price if price > 0 else self.mid


class MarketData(Protocol):
    def get_price(self, symbol: str) -> float: ...
    def get_close_on(self, symbol: str, day: date) -> float: ...
    def chain_with_greeks(self, symbol: str, expiration: str, option_type: str, num_strikes: int | None = None) -> pd.DataFrame:
        """Chain for one expiration with mid, re-derived IV, delta, theta and probability ITM per contract."""
        calls, puts = self.get_chain(symbol, expiration)
        df = (calls if option_type == "call" else puts).copy()
        spot = self.get_price(symbol)
        if num_strikes:
            df = df.iloc[(df["strike"] - spot).abs().argsort()[:num_strikes]]
        T = year_fraction(date.fromisoformat(expiration))
        rows = []
        for _, r in df.sort_values("strike").iterrows():
            bid, ask = float(r["bid"] or 0), float(r["ask"] or 0)
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(r["lastPrice"] or 0)
            iv = (implied_vol(mid, spot, r["strike"], T, option_type) if mid > 0 else None) or float(r["impliedVolatility"])
            g = greeks(spot, r["strike"], T, iv, option_type)
            rows.append({"strike": float(r["strike"]), "bid": bid, "ask": ask, "mid": round(mid, 2),
                         "iv": round(iv, 3), "delta": round(g.delta, 3), "theta": round(g.theta, 3),
                         "prob_itm": round(g.prob_itm, 3),
                         "open_interest": int(np.nan_to_num(r["openInterest"])),
                         "volume": int(np.nan_to_num(r["volume"]))})
        return pd.DataFrame(rows)

    def get_option_quote(self, symbol: str, option_type: str, strike: float, expiration: str) -> OptionQuote | None: ...
    def realized_vol(self, symbol: str, days: int = 30) -> float: ...


class _TTLCache:
    def __init__(self, ttl: float):
        self.ttl = ttl
        self._data: dict = {}

    def get(self, key, loader):
        hit = self._data.get(key)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        value = loader()
        self._data[key] = (time.time(), value)
        return value


class YahooMarket:
    def __init__(self, quote_ttl: float = 30, chain_ttl: float = 120):
        self._quotes = _TTLCache(quote_ttl)
        self._chains = _TTLCache(chain_ttl)
        self._slow = _TTLCache(3600)

    @staticmethod
    def _ticker(symbol: str) -> yf.Ticker:
        return yf.Ticker(symbol.upper().strip())

    def get_price(self, symbol: str) -> float:
        def load():
            price = self._ticker(symbol).fast_info["last_price"]
            if price is None or np.isnan(price):
                raise ValueError(f"No price available for {symbol!r}")
            return float(price)
        return self._quotes.get(("price", symbol.upper()), load)

    def get_quote(self, symbol: str) -> dict:
        info = self._ticker(symbol).fast_info
        price = self.get_price(symbol)
        prev = info["previous_close"]
        return {
            "symbol": symbol.upper(),
            "price": round(price, 2),
            "previous_close": round(prev, 2) if prev else None,
            "change_pct": round((price / prev - 1) * 100, 2) if prev else None,
            "year_high": round(info["year_high"], 2),
            "year_low": round(info["year_low"], 2),
            "realized_vol_30d": round(self.realized_vol(symbol), 4),
        }

    def get_history(self, symbol: str, period: str = "6mo") -> pd.DataFrame:
        return self._slow.get(("hist", symbol.upper(), period), lambda: self._ticker(symbol).history(period=period))

    def get_close_on(self, symbol: str, day: date) -> float:
        hist = self._ticker(symbol).history(start=day - timedelta(days=7), end=day + timedelta(days=1))
        if hist.empty:
            return self.get_price(symbol)
        return float(hist["Close"].iloc[-1])

    def realized_vol(self, symbol: str, days: int = 30) -> float:
        closes = self.get_history(symbol, "6mo")["Close"]
        returns = np.log(closes / closes.shift(1)).dropna().tail(days)
        return float(returns.std() * np.sqrt(252)) if len(returns) > 2 else 0.3

    def get_expirations(self, symbol: str) -> list[str]:
        return list(self._slow.get(("exp", symbol.upper()), lambda: self._ticker(symbol).options))

    def get_chain(self, symbol: str, expiration: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        def load():
            chain = self._ticker(symbol).option_chain(expiration)
            return chain.calls, chain.puts
        return self._chains.get(("chain", symbol.upper(), expiration), load)

    def chain_with_greeks(self, symbol: str, expiration: str, option_type: str, num_strikes: int | None = None) -> pd.DataFrame:
        """Chain for one expiration with mid, re-derived IV, delta, theta and probability ITM per contract."""
        calls, puts = self.get_chain(symbol, expiration)
        df = (calls if option_type == "call" else puts).copy()
        spot = self.get_price(symbol)
        if num_strikes:
            df = df.iloc[(df["strike"] - spot).abs().argsort()[:num_strikes]]
        T = year_fraction(date.fromisoformat(expiration))
        rows = []
        for _, r in df.sort_values("strike").iterrows():
            bid, ask = float(r["bid"] or 0), float(r["ask"] or 0)
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(r["lastPrice"] or 0)
            iv = (implied_vol(mid, spot, r["strike"], T, option_type) if mid > 0 else None) or float(r["impliedVolatility"])
            g = greeks(spot, r["strike"], T, iv, option_type)
            rows.append({"strike": float(r["strike"]), "bid": bid, "ask": ask, "mid": round(mid, 2),
                         "iv": round(iv, 3), "delta": round(g.delta, 3), "theta": round(g.theta, 3),
                         "prob_itm": round(g.prob_itm, 3),
                         "open_interest": int(np.nan_to_num(r["openInterest"])),
                         "volume": int(np.nan_to_num(r["volume"]))})
        return pd.DataFrame(rows)

    def get_option_quote(self, symbol: str, option_type: str, strike: float, expiration: str) -> OptionQuote | None:
        try:
            calls, puts = self.get_chain(symbol, expiration)
        except Exception:
            return None
        df = calls if option_type == "call" else puts
        row = df[np.isclose(df["strike"], strike)]
        if row.empty:
            return None
        r = row.iloc[0]
        quote = OptionQuote(
            bid=float(r["bid"] or 0), ask=float(r["ask"] or 0), last=float(r["lastPrice"] or 0),
            iv=float(r["impliedVolatility"] or 0),
            open_interest=int(np.nan_to_num(r["openInterest"])), volume=int(np.nan_to_num(r["volume"])),
        )
        # Yahoo's IV field is unreliable outside market hours; re-derive it from the mid when possible.
        spot = self.get_price(symbol)
        T = year_fraction(date.fromisoformat(expiration))
        solved = implied_vol(quote.mid, spot, strike, T, option_type) if quote.mid > 0 else None
        if solved:
            quote.iv = solved
        elif quote.iv < 0.01:
            quote.iv = self.realized_vol(symbol)
        return quote

    def get_option_mark(self, symbol: str, option_type: str, strike: float, expiration: str) -> float:
        """Mid price from the chain, or a Black-Scholes estimate from realized vol if unavailable."""
        quote = self.get_option_quote(symbol, option_type, strike, expiration)
        if quote and quote.mid > 0:
            return quote.mid
        T = year_fraction(date.fromisoformat(expiration))
        return bs_price(self.get_price(symbol), strike, T, self.realized_vol(symbol), option_type)

    def get_news(self, symbol: str, limit: int = 20) -> list[dict]:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol.upper()}&region=US&lang=en-US"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        items = []
        for item in ET.fromstring(resp.content).iter("item"):
            items.append({
                "title": (item.findtext("title") or "").strip(),
                "summary": (item.findtext("description") or "").strip(),
                "url": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
            })
        return items[:limit]

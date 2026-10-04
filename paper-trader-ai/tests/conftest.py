from datetime import date, timedelta

import pytest

from trader.db import connect
from trader.market import OptionQuote
from trader.portfolio import Portfolio


class FakeMarket:
    def __init__(self):
        self.prices = {"AAPL": 100.0}
        self.option_quotes = {}  # (symbol, type, strike, exp) -> OptionQuote
        self.closes = {}

    def get_price(self, symbol):
        return self.prices[symbol]

    def get_close_on(self, symbol, day):
        return self.closes.get((symbol, day), self.prices[symbol])

    def get_option_quote(self, symbol, option_type, strike, expiration):
        return self.option_quotes.get((symbol, option_type, float(strike), expiration))

    def realized_vol(self, symbol, days=30):
        return 0.3

    def set_option(self, symbol, option_type, strike, expiration, bid, ask):
        self.option_quotes[(symbol, option_type, float(strike), expiration)] = OptionQuote(bid, ask, (bid + ask) / 2, 0.3)


@pytest.fixture
def market():
    return FakeMarket()


@pytest.fixture
def pf(market):
    return Portfolio(connect(":memory:", 100_000.0), market, commission=0.65)


@pytest.fixture
def expiry():
    return (date.today() + timedelta(days=30)).isoformat()

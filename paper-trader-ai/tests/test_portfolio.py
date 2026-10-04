from datetime import date, timedelta

import pytest

from trader.portfolio import Order, OrderError


def stock(action, qty, symbol="AAPL"):
    return Order("stock", action, symbol, qty)


def opt(action, qty, otype, strike, expiry, symbol="AAPL"):
    return Order("option", action, symbol, qty, otype, strike, expiry)


def test_buy_and_sell_stock_realizes_pnl(pf, market):
    pf.execute(stock("buy", 10))
    market.prices["AAPL"] = 110.0
    fill = pf.execute(stock("sell", 4))
    assert fill.realized_pnl == pytest.approx(40.0)
    assert pf.stock_qty("AAPL") == 6
    assert pf.cash() == pytest.approx(100_000 - 1000 + 440)


def test_average_cost(pf, market):
    pf.execute(stock("buy", 10))
    market.prices["AAPL"] = 120.0
    pf.execute(stock("buy", 10))
    assert pf.stocks()[0]["avg_cost"] == pytest.approx(110.0)


def test_cannot_overspend_or_oversell(pf):
    with pytest.raises(OrderError, match="buying power"):
        pf.execute(stock("buy", 2000))
    with pytest.raises(OrderError, match="sell"):
        pf.execute(stock("sell", 1))


def test_covered_call_requires_shares(pf, market, expiry):
    market.set_option("AAPL", "call", 105, expiry, 2.0, 2.2)
    with pytest.raises(OrderError, match="Covered calls"):
        pf.execute(opt("sell_to_open", 1, "call", 105, expiry))
    pf.execute(stock("buy", 100))
    fill = pf.execute(opt("sell_to_open", 1, "call", 105, expiry))
    assert fill.price == 2.0  # sold at the bid
    assert fill.cash_delta == pytest.approx(200 - 0.65)
    # The 100 shares are now committed and can't be sold.
    with pytest.raises(OrderError):
        pf.execute(stock("sell", 1))


def test_cash_secured_put_reserves_collateral(pf, market, expiry):
    market.set_option("AAPL", "put", 95, expiry, 1.5, 1.6)
    pf.execute(opt("sell_to_open", 2, "put", 95, expiry))
    assert pf.put_collateral() == 19_000
    assert pf.buying_power() == pytest.approx(pf.cash() - 19_000)
    with pytest.raises(OrderError, match="Cash-secured"):
        pf.execute(opt("sell_to_open", 9, "put", 95, expiry))


def test_buy_to_close_short_call(pf, market, expiry):
    market.set_option("AAPL", "call", 105, expiry, 2.0, 2.2)
    pf.execute(stock("buy", 100))
    pf.execute(opt("sell_to_open", 1, "call", 105, expiry))
    market.set_option("AAPL", "call", 105, expiry, 0.4, 0.5)
    fill = pf.execute(opt("buy_to_close", 1, "call", 105, expiry))
    assert fill.price == 0.5  # bought at the ask
    assert fill.realized_pnl == pytest.approx((2.0 - 0.5) * 100 - 0.65)
    assert pf.options() == []


def test_covered_call_assignment(pf, market):
    exp = (date.today() - timedelta(days=1)).isoformat()
    market.set_option("AAPL", "call", 105, exp, 2.0, 2.2)
    pf.execute(stock("buy", 100))
    pf.conn.execute(  # open the position directly since the expiry is already in the past
        "INSERT INTO option_positions (symbol, option_type, strike, expiration, qty, avg_price, opened_at) "
        "VALUES ('AAPL', 'call', 105, ?, -1, 2.0, 'x')", (exp,))
    market.closes[("AAPL", date.fromisoformat(exp))] = 112.0
    events = pf.process_expirations()
    assert "called away" in events[0]
    assert pf.stock_qty("AAPL") == 0
    assert pf.options() == []
    assert pf.realized_pnl() == pytest.approx(200 + 500)  # premium kept + (105 - 100) * 100


def test_put_assignment_and_worthless_expiry(pf, market):
    exp = (date.today() - timedelta(days=1)).isoformat()
    for strike in (95, 80):
        pf.conn.execute(
            "INSERT INTO option_positions (symbol, option_type, strike, expiration, qty, avg_price, opened_at) "
            "VALUES ('AAPL', 'put', ?, ?, -1, 1.5, 'x')", (strike, exp))
    market.closes[("AAPL", date.fromisoformat(exp))] = 90.0
    cash_before = pf.cash()
    events = pf.process_expirations()
    assert any("bought 100 shares at 95" in e for e in events)
    assert any("expired worthless" in e for e in events)
    assert pf.stock_qty("AAPL") == 100
    assert pf.stocks()[0]["avg_cost"] == 95
    assert pf.cash() == pytest.approx(cash_before - 9_500)


def test_snapshot_totals(pf, market, expiry):
    market.set_option("AAPL", "call", 105, expiry, 2.0, 2.2)
    pf.execute(stock("buy", 100))
    pf.execute(opt("sell_to_open", 1, "call", 105, expiry))
    snap = pf.snapshot()
    assert snap["stock_value"] == 10_000
    assert snap["option_value"] == pytest.approx(-210)  # short call marked at mid 2.10
    assert snap["equity"] == pytest.approx(snap["cash"] + 10_000 - 210)
    assert snap["options"][0]["strategy"] == "covered_call"


def test_pending_orders(pf):
    pid = pf.add_pending(stock("buy", 5), "test")
    assert len(pf.pending()) == 1
    fill = pf.resolve_pending(pid, approve=True)
    assert fill.trade_id and pf.stock_qty("AAPL") == 5
    assert pf.pending() == []

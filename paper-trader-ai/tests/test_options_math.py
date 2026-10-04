from datetime import date, timedelta
from math import exp, isclose

import numpy as np

from trader.options_math import analyze_strategy, bs_price, greeks, implied_vol, payoff_at_expiry


def test_put_call_parity():
    S, K, T, sigma, r = 100, 105, 0.5, 0.25, 0.04
    c, p = bs_price(S, K, T, sigma, "call", r), bs_price(S, K, T, sigma, "put", r)
    assert isclose(c - p, S - K * exp(-r * T), abs_tol=1e-9)


def test_greeks_signs_and_bounds():
    call, put = greeks(100, 100, 0.25, 0.3, "call"), greeks(100, 100, 0.25, 0.3, "put")
    assert 0.5 < call.delta < 0.6 and -0.5 < put.delta < -0.4
    assert call.gamma > 0 and call.vega > 0 and call.theta < 0
    assert isclose(call.delta - put.delta, 1.0, abs_tol=1e-9)


def test_implied_vol_round_trip():
    price = bs_price(100, 110, 0.3, 0.42, "call")
    assert isclose(implied_vol(price, 100, 110, 0.3, "call"), 0.42, abs_tol=1e-4)


def test_covered_call_metrics():
    exp_date = date.today() + timedelta(days=30)
    m = analyze_strategy("covered_call", spot=100, strike=105, premium=2.0, expiration=exp_date, iv=0.3)
    assert m["breakeven"] == 98.0
    assert m["max_profit"] == 700.0  # (105 - 100 + 2) * 100
    assert m["static_return_pct"] == 2.0
    assert m["if_called_return_pct"] == 7.0


def test_cash_secured_put_metrics():
    exp_date = date.today() + timedelta(days=30)
    m = analyze_strategy("cash_secured_put", spot=100, strike=95, premium=1.5, expiration=exp_date, iv=0.3)
    assert m["capital_required"] == 9500.0
    assert m["effective_purchase_price"] == 93.5
    assert m["max_profit"] == 150.0


def test_payoff_curves():
    prices = np.array([80.0, 100.0, 120.0])
    cc = payoff_at_expiry("covered_call", prices, spot=100, strike=105, premium=2)
    assert list(cc) == [-1800.0, 200.0, 700.0]
    csp = payoff_at_expiry("cash_secured_put", prices, spot=100, strike=95, premium=1.5)
    assert list(csp) == [-1350.0, 150.0, 150.0]

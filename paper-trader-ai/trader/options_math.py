"""Black-Scholes pricing, Greeks, and strategy analytics for European-style options.

US equity options are American-style, but for non-dividend-paying calls and
short-dated contracts Black-Scholes is a reasonable approximation for paper trading.
"""
from dataclasses import dataclass
from datetime import date
from math import exp, log, sqrt

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

from .config import CONTRACT_SIZE, RISK_FREE_RATE


def year_fraction(expiration: date, today: date | None = None) -> float:
    """Time to expiry in years. Options expire at the close, so expiration day counts as half a day."""
    today = today or date.today()
    return max((expiration - today).days + 0.5, 0.0) / 365.0


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
    return d1, d1 - sigma * sqrt(T)


def bs_price(S: float, K: float, T: float, sigma: float, option_type: str, r: float = RISK_FREE_RATE) -> float:
    if T <= 0 or sigma <= 0:
        return intrinsic(S, K, option_type)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return S * norm.cdf(d1) - K * exp(-r * T) * norm.cdf(d2)
    return K * exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def intrinsic(S: float, K: float, option_type: str) -> float:
    return max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)


@dataclass
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float  # per calendar day, per share
    vega: float  # per 1 vol point (1%), per share
    prob_itm: float  # risk-neutral probability of finishing in the money


def greeks(S: float, K: float, T: float, sigma: float, option_type: str, r: float = RISK_FREE_RATE) -> Greeks:
    if T <= 0 or sigma <= 0:
        itm = intrinsic(S, K, option_type) > 0
        delta = (1.0 if itm else 0.0) if option_type == "call" else (-1.0 if itm else 0.0)
        return Greeks(intrinsic(S, K, option_type), delta, 0.0, 0.0, 0.0, float(itm))
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    pdf = norm.pdf(d1)
    gamma = pdf / (S * sigma * sqrt(T))
    vega = S * pdf * sqrt(T) / 100
    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (-S * pdf * sigma / (2 * sqrt(T)) - r * K * exp(-r * T) * norm.cdf(d2)) / 365
        prob_itm = norm.cdf(d2)
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S * pdf * sigma / (2 * sqrt(T)) + r * K * exp(-r * T) * norm.cdf(-d2)) / 365
        prob_itm = norm.cdf(-d2)
    return Greeks(bs_price(S, K, T, sigma, option_type, r), delta, gamma, theta, vega, prob_itm)


def implied_vol(price: float, S: float, K: float, T: float, option_type: str, r: float = RISK_FREE_RATE) -> float | None:
    """Solve for the volatility that reproduces an observed option price. None if no solution."""
    if T <= 0 or price <= intrinsic(S, K, option_type) * exp(-r * T):
        return None
    try:
        return brentq(lambda s: bs_price(S, K, T, s, option_type, r) - price, 1e-4, 5.0, xtol=1e-6)
    except ValueError:
        return None


STRATEGIES = ("covered_call", "cash_secured_put", "long_call", "long_put")


def analyze_strategy(
    strategy: str,
    spot: float,
    strike: float,
    premium: float,
    expiration: date,
    iv: float,
    contracts: int = 1,
    today: date | None = None,
) -> dict:
    """Return risk/reward metrics for a single-leg (or stock + option) strategy at expiration."""
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}")
    option_type = "call" if strategy in ("covered_call", "long_call") else "put"
    dte = max((expiration - (today or date.today())).days, 0)
    T = year_fraction(expiration, today)
    g = greeks(spot, strike, T, iv, option_type)
    shares = contracts * CONTRACT_SIZE
    annualize = 365 / max(dte, 1)
    out = {
        "strategy": strategy,
        "spot": round(spot, 2),
        "strike": strike,
        "premium_per_share": round(premium, 2),
        "premium_total": round(premium * shares, 2),
        "days_to_expiration": dte,
        "implied_vol": round(iv, 4),
        "delta_per_contract": round(g.delta, 3),
        "theta_per_day_total": round(g.theta * shares, 2),
        "prob_itm_at_expiry": round(g.prob_itm, 3),
    }
    if strategy == "covered_call":
        static = premium / spot
        called = (strike - spot + premium) / spot
        out |= {
            "capital_required": round(spot * shares, 2),
            "breakeven": round(spot - premium, 2),
            "max_profit": round((strike - spot + premium) * shares, 2),
            "max_loss": round((spot - premium) * shares, 2),
            "static_return_pct": round(static * 100, 2),
            "if_called_return_pct": round(called * 100, 2),
            "annualized_static_return_pct": round(static * annualize * 100, 1),
            "downside_protection_pct": round(static * 100, 2),
            "prob_shares_called_away": round(g.prob_itm, 3),
        }
    elif strategy == "cash_secured_put":
        ret = premium / strike
        out |= {
            "capital_required": round(strike * shares, 2),
            "breakeven": round(strike - premium, 2),
            "effective_purchase_price": round(strike - premium, 2),
            "max_profit": round(premium * shares, 2),
            "max_loss": round((strike - premium) * shares, 2),
            "return_on_collateral_pct": round(ret * 100, 2),
            "annualized_return_pct": round(ret * annualize * 100, 1),
            "prob_assignment": round(g.prob_itm, 3),
        }
    elif strategy == "long_call":
        out |= {
            "capital_required": round(premium * shares, 2),
            "breakeven": round(strike + premium, 2),
            "max_profit": "unlimited",
            "max_loss": round(premium * shares, 2),
        }
    else:
        out |= {
            "capital_required": round(premium * shares, 2),
            "breakeven": round(strike - premium, 2),
            "max_profit": round((strike - premium) * shares, 2),
            "max_loss": round(premium * shares, 2),
        }
    return out


def payoff_at_expiry(strategy: str, prices: np.ndarray, spot: float, strike: float, premium: float, contracts: int = 1) -> np.ndarray:
    """Total P&L at expiration across a range of underlying prices."""
    shares = contracts * CONTRACT_SIZE
    call = np.maximum(prices - strike, 0)
    put = np.maximum(strike - prices, 0)
    per_share = {
        "covered_call": (prices - spot) + premium - call,
        "cash_secured_put": premium - put,
        "long_call": call - premium,
        "long_put": put - premium,
    }[strategy]
    return per_share * shares

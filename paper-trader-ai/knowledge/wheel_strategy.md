# The Wheel Strategy

## Overview
The wheel combines cash-secured puts and covered calls into a repeating cycle:
1. Sell a cash-secured put on a stock you want to own.
2. If it expires worthless, keep the premium and sell another put.
3. If assigned, you now own 100 shares at the strike (cost basis = strike - premiums collected).
4. Sell covered calls against the shares, ideally at strikes above your cost basis.
5. If the calls expire worthless, keep the premium and sell another call. If the shares are called away, you are back to cash, so return to step 1.

## Tracking cost basis
Track your adjusted cost basis: share purchase price minus all put and call premiums collected during the cycle. Selling calls above the adjusted basis keeps the full cycle profitable even if the shares are called away.

## When it works and when it doesn't
- It works best on fundamentally solid, liquid stocks with active options markets, in sideways to mildly rising markets.
- It struggles in strong downtrends. You get assigned, and then cannot sell calls above your basis without accepting very low premium.
- In strong uptrends, it lags simply holding the stock, because shares get called away.

## Position sizing for the wheel
- Keep any single wheel position to roughly 5-10% of the account, so that assignment doesn't create an outsized concentration.
- Keep a cash reserve so you aren't forced to close positions at a bad time.

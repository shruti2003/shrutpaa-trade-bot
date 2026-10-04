# Cash-Secured Puts

## What it is
A cash-secured put (CSP) means selling a put option while setting aside enough cash to buy 100 shares per contract at the strike price. You collect premium up front. If the stock is below the strike at expiration, you are assigned: you must buy 100 shares per contract at the strike. In effect, you are being paid to place a limit buy order below the current price.

## Payoff and key numbers
- Collateral required = strike x 100 per contract. That cash is reserved and cannot be used for other trades.
- Max profit = premium x 100. You keep it if the stock stays above the strike.
- Breakeven / effective purchase price = strike - premium.
- Max loss = (strike - premium) x 100, if the stock goes to zero.
- Return on collateral = premium / strike. Annualized = that x 365 / DTE.
- Probability of assignment is roughly the absolute value of the put's delta.

## Choosing a strike and expiration
- Only sell puts on stocks you actually want to own, at a price you would be happy paying.
- A delta of 0.20-0.30 (about 70-80% chance of expiring worthless) is a common choice. Strikes near support levels are also popular.
- 30-45 DTE balances premium against time decay. Higher implied volatility means more premium, but usually because the market expects bigger moves.

## Managing the position
- Close early at 50-75% of max profit to cut the tail risk and recycle the collateral.
- Rolling: if the stock drops toward the strike, buy back the put and sell a later, lower strike put for a net credit. This delays assignment and lowers your potential cost basis.
- If assigned, your cost basis is effectively the strike minus the premium. From there, many traders move into covered calls (the wheel).

## Risks
- You can be assigned shares at a price well above the market after a sharp drop. The loss is like buying the stock at the strike.
- The upside is capped at the premium. If the stock rallies, you miss the gains.
- Tying up large amounts of cash in one name creates concentration risk. Size each CSP so that being assigned keeps the position a reasonable share of your portfolio.

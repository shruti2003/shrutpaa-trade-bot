# Covered Calls

## What it is
A covered call means owning at least 100 shares of a stock and selling (writing) one call option against each 100 shares. You collect the option premium up front. In exchange, you agree to sell your shares at the strike price if the buyer exercises, which usually happens when the stock is above the strike at expiration. The shares "cover" the obligation, so the risk is the same as owning the stock, minus the premium received.

## Payoff and key numbers
- Max profit = (strike - stock purchase price + premium) x 100 per contract. It is reached if the stock is at or above the strike at expiration.
- Breakeven = stock purchase price - premium received.
- Max loss = (stock purchase price - premium) x 100, if the stock goes to zero. The premium only cushions the downside a little.
- Static return = premium / stock price. This is your return if the stock finishes exactly where it is.
- If-called return = (strike - stock price + premium) / stock price. This is your return if the shares are called away.
- Annualized return = return x (365 / days to expiration). Use it to compare different expirations fairly.

## Choosing a strike
- Out-of-the-money (OTM) strikes, above the current price, pay less premium but leave room for the stock to rise. They also make assignment less likely.
- At-the-money (ATM) strikes pay the most time value, but are roughly 50% likely to be assigned.
- In-the-money (ITM) strikes give more downside protection but little upside. They work mostly as a slow exit.
- A common rule of thumb is to sell calls with a delta of 0.20-0.35. The delta roughly approximates the probability of finishing in the money, so this means about a 65-80% chance of keeping your shares.
- Never sell a strike below your cost basis unless you are happy to lock in a loss if called away.

## Choosing an expiration
- 30-45 days to expiration (DTE) is a common sweet spot. Time decay (theta) speeds up in the final month, while you still get meaningful premium.
- Weekly options decay fastest and annualize well, but require more active management and more commissions.
- Avoid holding through earnings unless intended: implied volatility (and premium) is higher, but so is the chance of a big move through your strike.

## Managing the position
- Close early: buying back the call after capturing 50-80% of the premium frees up the shares to sell a new call. This often improves risk-adjusted returns.
- Rolling: if the stock rises toward the strike and you want to keep the shares, buy back the call and sell a later-dated, higher strike call. Try to do this for a net credit.
- If the stock falls sharply, the call becomes nearly worthless. You can buy it back cheaply and re-sell a lower strike, but be careful not to go below cost basis.
- Assignment can happen early on American-style options, especially just before an ex-dividend date when the call is deep ITM.

## Risks and misconceptions
- Covered calls cap your upside. In a strong rally, you can badly underperform simply holding the stock.
- They do not protect against large drops. The premium is a small cushion.
- Premium is not "free income". It is payment for selling your upside, and higher premium means higher implied risk.
- Covered calls are best on stocks you are comfortable holding long-term, in flat to mildly bullish markets.

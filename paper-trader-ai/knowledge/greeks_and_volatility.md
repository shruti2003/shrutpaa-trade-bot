# Option Greeks and Volatility

## Delta
Delta is how much the option price changes for a $1 move in the stock. Calls range from 0 to 1, puts from 0 to -1. Delta is also a rough estimate of the probability of finishing in the money. Position delta = delta x 100 x contracts, which is the equivalent share exposure. A covered call position has delta = 100 shares minus 100 x the call's delta per contract.

## Gamma
Gamma is how fast delta changes as the stock moves. It is highest for at-the-money options near expiration. Short options carry negative gamma: moves against you speed up, which is why short-dated ATM short options can swing quickly.

## Theta
Theta is the time decay per day. Option sellers (covered calls, CSPs) have positive theta and earn decay. Buyers have negative theta. Decay speeds up in the last 30 days, and is fastest for ATM options.

## Vega and implied volatility
Vega is the price change for a 1-point change in implied volatility (IV). IV is the market's expectation of future movement. It is backed out from option prices using a model such as Black-Scholes. High IV means rich premiums for sellers and expensive options for buyers. IV usually spikes before earnings and collapses afterward (the "IV crush"), which hurts long option holders even when they guess the direction right.

## Realized vs implied volatility
Realized (historical) volatility measures how much the stock actually moved, as the annualized standard deviation of daily log returns. When IV is well above realized vol, options are relatively expensive, which favors selling. When IV is below realized vol, options are cheap, which favors buying.

## Black-Scholes basics
The Black-Scholes model prices European options from the stock price, strike, time, risk-free rate, and volatility. US stock options are American-style (early exercise allowed), but Black-Scholes is a good approximation for most short-dated, non-dividend cases. N(d2) approximates the risk-neutral probability that a call finishes in the money.

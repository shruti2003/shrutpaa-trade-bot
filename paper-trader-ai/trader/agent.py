"""Claude-powered trading copilot: tool use over the portfolio, live market data, and the RAG knowledge base."""
import functools
import json
from collections.abc import Iterator
from datetime import date
from typing import Literal

import anthropic
from anthropic import beta_tool

from . import ingest
from .config import MODEL
from .market import YahooMarket
from .options_math import analyze_strategy
from .portfolio import Order, OrderError, Portfolio
from .rag import KnowledgeBase

SYSTEM_PROMPT = """You are the copilot inside a paper-trading app. The user trades with simulated money \
(they started with a fixed cash balance) but wants to manage it exactly as if it were real, to build skill \
and discipline. They trade stocks and single-leg options: covered calls, cash-secured puts, and long calls/puts.

How to work:
- Ground every number in tool results. Call get_portfolio before advising on the user's positions, and fetch \
quotes/chains before discussing specific contracts. Never invent prices, Greeks, or news.
- Use search_knowledge for strategy questions, for questions about the user's own past trades and journal, and \
for news/filings context. If news or filings for a ticker are missing or stale, call refresh_research first. \
Cite what you used inline, e.g. [journal: Trade #12 AAPL] or [filing: MSFT 10-K - Risk Factors].
- When suggesting a trade, show the math (premium, breakeven, return on capital, annualized return, probability \
of assignment, max loss) and size it against buying power and concentration. Prefer analyze_option_strategy for this.
- To act on a trade, call propose_trade. Depending on settings it is either queued for the user's approval or \
executed immediately; report exactly what the tool said happened. Only propose trades the user asked for or agreed to.
- Be direct about risk: covered calls cap upside and don't protect against large drops; cash-secured puts \
can assign shares at a price above market; long options decay with time.
- Keep answers tight. Use short tables for comparisons of strikes or expirations.

Today's date is {today}."""


def _safe(fn):
    """Turn expected failures into readable tool output instead of crashing the agent loop."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (OrderError, ValueError, KeyError) as e:
            return f"Error: {e}"
    return wrapper


def _dump(obj) -> str:
    return json.dumps(obj, default=str)


class TradingAgent:
    def __init__(self, portfolio: Portfolio, market: YahooMarket, kb: KnowledgeBase,
                 auto_execute: bool = False, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.portfolio = portfolio
        self.market = market
        self.kb = kb
        self.auto_execute = auto_execute
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.tools = self._build_tools()

    def _build_tools(self) -> list:
        pf, market, kb = self.portfolio, self.market, self.kb

        @beta_tool
        @_safe
        def get_portfolio() -> str:
            """Get the paper account: cash, buying power, equity, P&L, every stock and option position marked to market with Greeks."""
            return _dump(pf.snapshot())

        @beta_tool
        @_safe
        def get_quote(symbol: str) -> str:
            """Get the latest (15-min delayed) stock quote, day change, 52-week range and 30-day realized volatility.

            Args:
                symbol: Ticker symbol, e.g. AAPL.
            """
            return _dump(market.get_quote(symbol))

        @beta_tool
        @_safe
        def list_option_expirations(symbol: str) -> str:
            """List available option expiration dates for a ticker.

            Args:
                symbol: Ticker symbol.
            """
            exps = market.get_expirations(symbol)
            today = date.today()
            return _dump([{"expiration": e, "dte": (date.fromisoformat(e) - today).days} for e in exps[:16]])

        @beta_tool
        @_safe
        def get_option_chain(symbol: str, expiration: str, option_type: Literal["call", "put"], num_strikes: int = 10) -> str:
            """Get the option chain near the money for one expiration, with bid/ask, implied vol, delta, and open interest.

            Args:
                symbol: Ticker symbol.
                expiration: Expiration date YYYY-MM-DD (from list_option_expirations).
                option_type: "call" or "put".
                num_strikes: How many strikes closest to the current price to return.
            """
            rows = market.chain_with_greeks(symbol, expiration, option_type, num_strikes).to_dict("records")
            spot = market.get_price(symbol)
            return _dump({"symbol": symbol.upper(), "spot": round(spot, 2), "expiration": expiration,
                          "dte": (date.fromisoformat(expiration) - date.today()).days, "type": option_type,
                          "contracts": rows})

        @beta_tool
        @_safe
        def analyze_option_strategy(
            symbol: str,
            strategy: Literal["covered_call", "cash_secured_put", "long_call", "long_put"],
            strike: float,
            expiration: str,
            contracts: int = 1,
        ) -> str:
            """Analyze a specific options trade using the live quote: premium, breakeven, max profit/loss, returns, annualized yield, probability of assignment, and whether the account can place it.

            Args:
                symbol: Ticker symbol.
                strategy: One of covered_call, cash_secured_put, long_call, long_put.
                strike: Strike price.
                expiration: Expiration date YYYY-MM-DD.
                contracts: Number of contracts (each is 100 shares).
            """
            option_type = "call" if strategy in ("covered_call", "long_call") else "put"
            quote = market.get_option_quote(symbol, option_type, strike, expiration)
            if quote is None:
                return f"Error: no {option_type} at strike {strike} expiring {expiration}. Check get_option_chain."
            side = "sell" if strategy in ("covered_call", "cash_secured_put") else "buy"
            premium = quote.fill_price(side)
            result = analyze_strategy(strategy, market.get_price(symbol), strike, premium,
                                      date.fromisoformat(expiration), quote.iv, contracts)
            result["fill_assumption"] = f"{side} at {'bid' if side == 'sell' else 'ask'} {premium:.2f}"
            action = "sell_to_open" if side == "sell" else "buy_to_open"
            try:
                pf.preview(Order("option", action, symbol, contracts, option_type, strike, expiration))
                result["account_can_place"] = True
            except OrderError as e:
                result["account_can_place"] = False
                result["blocked_reason"] = str(e)
            if strategy == "covered_call":
                result["shares_owned"] = pf.stock_qty(symbol)
                result["free_shares"] = pf.free_shares(symbol)
            result["buying_power"] = round(pf.buying_power(), 2)
            return _dump(result)

        @beta_tool
        @_safe
        def search_knowledge(query: str, sources: list[Literal["strategy", "journal", "news", "filing"]] | None = None,
                             symbol: str | None = None, k: int = 6) -> str:
            """Semantic search over the knowledge base: options strategy guides, the user's trade journal, recent news, and SEC filing excerpts.

            Args:
                query: Natural-language search query.
                sources: Restrict to these sources. Omit to search everything.
                symbol: Restrict to one ticker (applies to journal, news, filing).
                k: Number of passages to return.
            """
            hits = kb.search(query, k=k, sources=sources, symbol=symbol)
            if not hits:
                return "No matching passages. For news/filings, try refresh_research first."
            return _dump([{"citation": h.citation(), "score": h.score, "url": h.url, "text": h.text} for h in hits])

        @beta_tool
        @_safe
        def refresh_research(symbol: str, include_filing: bool = False, filing_form: Literal["10-K", "10-Q"] = "10-K") -> str:
            """Fetch the latest news headlines (and optionally the latest SEC 10-K or 10-Q excerpts) for a ticker into the knowledge base.

            Args:
                symbol: Ticker symbol.
                include_filing: Also download and index the latest SEC filing (slower).
                filing_form: Which filing to fetch, 10-K (annual) or 10-Q (quarterly).
            """
            out = {"news_chunks": ingest.ingest_news(kb, market, symbol)}
            if include_filing:
                out["filing_chunks"] = ingest.ingest_filing(kb, symbol, filing_form)
            return _dump(out)

        @beta_tool
        @_safe
        def propose_trade(
            asset_type: Literal["stock", "option"],
            action: Literal["buy", "sell", "buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"],
            symbol: str,
            quantity: int,
            rationale: str,
            option_type: Literal["call", "put"] | None = None,
            strike: float | None = None,
            expiration: str | None = None,
        ) -> str:
            """Place (or queue for user approval) a paper trade. Stocks use buy/sell; options use buy_to_open, sell_to_open, buy_to_close, sell_to_close. Sell-to-open calls must be covered by shares; sell-to-open puts must be cash-secured.

            Args:
                asset_type: "stock" or "option".
                action: Order action.
                symbol: Ticker symbol.
                quantity: Shares for stock, contracts for options.
                rationale: One or two sentences on why, saved to the trade journal.
                option_type: "call" or "put" (options only).
                strike: Strike price (options only).
                expiration: Expiration YYYY-MM-DD (options only).
            """
            order = Order(asset_type, action, symbol, quantity, option_type, strike, expiration, note=rationale)
            preview = pf.preview(order)
            if self.auto_execute:
                fill = pf.execute(order)
                pf.add_journal(f"AI trade: {order.describe()}. Rationale: {rationale}", order.symbol, fill.trade_id)
                ingest.ingest_journal(kb, pf)
                return _dump({"status": "executed", "order": order.describe(), "fill_price": fill.price,
                              "fees": fill.fees, "cash_delta": round(fill.cash_delta, 2), "trade_id": fill.trade_id})
            pending_id = pf.add_pending(order, rationale)
            return _dump({"status": "queued_for_user_approval", "pending_id": pending_id, "order": order.describe(),
                          "estimated_price": preview.price, "estimated_cash_delta": round(preview.cash_delta, 2),
                          "note": "The user must click Approve in the app before this executes."})

        @beta_tool
        @_safe
        def get_trade_history(limit: int = 25, symbol: str | None = None) -> str:
            """Get recent executed trades, newest first, with realized P&L.

            Args:
                limit: Max trades to return.
                symbol: Only trades for this ticker.
            """
            return _dump(pf.trades(limit=limit, symbol=symbol))

        @beta_tool
        @_safe
        def add_journal_note(text: str, symbol: str | None = None) -> str:
            """Save a note to the user's trade journal (thesis, lesson learned, plan). Only when the user asks.

            Args:
                text: The note.
                symbol: Related ticker, if any.
            """
            note_id = pf.add_journal(text, symbol)
            ingest.ingest_journal(kb, pf)
            return f"Saved journal note #{note_id}."

        return [get_portfolio, get_quote, list_option_expirations, get_option_chain, analyze_option_strategy,
                search_knowledge, refresh_research, propose_trade, get_trade_history, add_journal_note]

    def run(self, messages: list) -> Iterator:
        """Run one user turn. Appends assistant turns and tool results to `messages` and yields each model response."""
        runner = self.client.beta.messages.tool_runner(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT.format(today=date.today().isoformat()),
            tools=self.tools,
            messages=list(messages),
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},
            # If a safety classifier declines, the API retries on a suitable fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            max_iterations=20,
        )
        for message in runner:
            messages.append({"role": "assistant", "content": message.content})
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                messages.append(tool_response)
            yield message

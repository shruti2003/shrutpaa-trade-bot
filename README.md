[README.md](https://github.com/user-attachments/files/33015732/README.md)
# Paper Trader AI

Paper Trader AI is a paper-trading app for stocks and options. It includes an AI copilot built on Claude that uses tool calling and retrieval-augmented generation (RAG).

You trade with simulated money, but the rules are realistic: bid/ask fills, commissions, covered-call and cash-secured-put requirements, and assignment at expiration. That way you can practice managing a portfolio as if the money were real.

**Tech stack:** Python · Streamlit · Anthropic Claude API (tool use) · ChromaDB (vector search) · SQLite · yfinance · SEC EDGAR · Black-Scholes (SciPy) · Plotly · pytest

---

## Features

### Paper trading engine
- Starts with $100,000 of simulated cash. You can reset it to any amount.
- **Stocks:** market orders, average cost basis, realized and unrealized P&L.
- **Options:** buy to open, sell to open, buy to close, sell to close.
  - Buys fill at the **ask**, sells at the **bid**, plus **$0.65 per contract**.
  - **Covered calls** need 100 free shares per contract. Shares covering a call can't be sold.
  - **Cash-secured puts** set aside strike × 100 of cash from buying power.
- **Automatic expiration handling:**
  - Out-of-the-money options expire worthless.
  - In-the-money short calls are assigned: your shares are called away at the strike.
  - In-the-money short puts are assigned: you buy the shares at the strike.
  - In-the-money long options pay out their value in cash.

### Options Lab
- Live option chains with Greeks (delta, theta, chance of finishing in the money). Implied volatility is recalculated from the bid/ask midpoint.
- A strategy analyzer for **covered calls, cash-secured puts, long calls and long puts**:
  - premium, breakeven, max profit and max loss
  - static, if-called and annualized return
  - chance of assignment
  - a P&L-at-expiration chart
- Smart defaults: about 0.30 delta for selling strategies, at-the-money for buying, and about 30 days to expiration.
- Close any open option position with one click, with the estimated P&L shown first.

### Dashboard
- Equity, cash, buying power, realized P&L, net share exposure and portfolio theta (daily time decay).
- Allocation chart, equity curve, positions marked to market, and recent trades.

### AI Copilot (Claude)
The copilot is an agent with 10 tools:

| Tool | What it does |
|---|---|
| `get_portfolio` | Cash, buying power, positions and Greeks |
| `get_quote` | Price, day change, 52-week range, 30-day realized volatility |
| `list_option_expirations` / `get_option_chain` | Option chains near the current price, with Greeks |
| `analyze_option_strategy` | Full metrics for a specific trade, plus whether your account can place it |
| `search_knowledge` | RAG search over guides, your journal, news and filings |
| `refresh_research` | Pulls the latest news and SEC filings for a ticker |
| `propose_trade` | Queues a trade **for your approval**, or executes it if auto-execute is on |
| `get_trade_history` / `add_journal_note` | Reads your trade history and writes journal notes |

- **You stay in control:** AI trade ideas appear as Approve/Reject cards and don't run until you approve them.
- Answers are based on the tool results and cite sources, for example `[strategy: Covered Calls - Managing the position]`.

### RAG knowledge base
All chunks live in one ChromaDB collection. They're embedded on your machine with all-MiniLM-L6-v2, and search can be filtered by **source** and **ticker**.

| Source | Content |
|---|---|
| `strategy` | Guides in `knowledge/*.md` (covered calls, CSPs, the wheel, Greeks, long options, risk management) plus your own uploads |
| `journal` | Every trade, written out in plain English, plus your journal notes. You can ask things like *"what do my losing trades have in common?"* |
| `news` | Yahoo Finance headlines for each ticker |
| `filing` | Risk Factors and MD&A sections from the latest 10-K or 10-Q on SEC EDGAR |

### Journal & history
- Write notes and link them to trades.
- See win rate and realized P&L by strategy, and export everything to CSV.
- Everything is re-indexed into RAG automatically.

---

## Quick start

**Requirements:** Python 3.10+ and an [Anthropic API key](https://platform.claude.com). You only need the key for the AI Copilot page.

```bash
git clone <your-repo-url> paper-trader-ai && cd paper-trader-ai

# Install dependencies
uv venv && uv pip install -r requirements.txt
# or: python -m venv .venv && .venv/bin/pip install -r requirements.txt

# Configure secrets (.env is git-ignored)
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
SEC_USER_AGENT=Your Name you@email.com
EOF

# Run
.venv/bin/streamlit run app.py
```

The app opens at http://localhost:8501.

### Try this first
1. **Trade Stocks:** buy 100 shares of AAPL.
2. **Options Lab:** choose *Covered call*. Look at the analysis and the payoff chart, then place the trade.
3. **Knowledge Base:** fetch news and the 10-K for a ticker, then try the search playground.
4. **AI Copilot:** ask *"Review my portfolio and tell me my biggest risks"* or *"Compare 3 cash-secured put strikes on MSFT for next month."*
5. **Dashboard:** approve or reject any trades the AI proposed.

---

## Configuration

Set these in `.env` or as environment variables. Shell variables take priority over `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (none) | Claude API key |
| `PAPER_TRADER_MODEL` | `claude-opus-5-5` | Model for the copilot. `claude-sonnet-5-5` is about half the cost |
| `SEC_USER_AGENT` | `PaperTraderAI research@example.com` | The SEC requires automated clients to identify themselves |
| `PAPER_TRADER_DATA` | `./data` | Where the SQLite database and vector store are kept |

Starting cash, commission, and the risk-free rate are set in `trader/config.py`.

---

## Project structure

```
paper-trader-ai/
├── app.py                  # Streamlit entry point: navigation, sidebar, account reset
├── pages/
│   ├── dashboard.py        # Account metrics, positions, equity curve, pending AI orders
│   ├── stocks.py           # Quote, candlestick chart, stock orders
│   ├── options.py          # Chains, strategy analyzer, payoff chart, close positions
│   ├── assistant.py        # AI Copilot chat UI
│   ├── journal.py          # Journal, trade history, P&L by strategy
│   └── knowledge.py        # RAG ingestion and search playground
├── trader/
│   ├── portfolio.py        # Trading engine: validation, fills, P&L, expiration/assignment
│   ├── options_math.py     # Black-Scholes, Greeks, implied vol, strategy metrics
│   ├── market.py           # yfinance quotes/chains/history, news RSS, TTL cache
│   ├── rag.py              # Chunking, ChromaDB store, filtered semantic search
│   ├── ingest.py           # Loaders: strategy docs, journal, news, SEC filings
│   ├── agent.py            # Claude tool-use agent
│   ├── db.py               # SQLite schema
│   ├── config.py           # Settings and .env loading
│   ├── services.py         # Cached shared resources for Streamlit
│   └── ui.py               # Reusable UI widgets
├── knowledge/              # Strategy guides indexed into RAG
└── tests/                  # pytest suite
```

---

## Technical architecture

### Layered design
The app has three layers, and imports only point downward. The core trading logic doesn't depend on Streamlit at all, so it can be tested without a UI, and the UI could be swapped out (for example for a FastAPI + React frontend).

```
┌──────────────────────────────────────────────────────────────────────┐
│  PRESENTATION   app.py + pages/*.py (Streamlit multipage)            │
│                 ui.py widgets · services.py cached resources         │
├──────────────────────────────────────────────────────────────────────┤
│  AI LAYER       agent.py — TradingAgent                              │
│                 Claude Opus 5.5 · 10 typed tools · tool runner loop  │
├───────────────┬──────────────────┬──────────────────┬────────────────┤
│  DOMAIN       │ portfolio.py     │ options_math.py  │ rag.py         │
│               │ orders, fills,   │ Black-Scholes,   │ chunking,      │
│               │ P&L, assignment  │ Greeks, IV,      │ vector search  │
│               │                  │ strategy metrics │ ingest.py      │
├───────────────┼──────────────────┼──────────────────┼────────────────┤
│  DATA         │ SQLite (db.py)   │ market.py        │ ChromaDB       │
│               │ account, trades, │ yfinance, Yahoo  │ + MiniLM ONNX  │
│               │ positions        │ RSS, TTL cache   │ SEC EDGAR      │
└───────────────┴──────────────────┴──────────────────┴────────────────┘
```

### Data model (SQLite)

| Table | Purpose |
|---|---|
| `account` | A single row: cash and starting cash |
| `stock_positions` | Symbol, quantity, average cost |
| `option_positions` | Symbol, type, strike, expiration, **signed** quantity (+long / −short), average premium |
| `trades` | Append-only log of every fill, including fees, cash change, realized P&L, strategy tag and note |
| `journal` | Free-form notes, optionally linked to a trade |
| `pending_orders` | AI-proposed orders waiting for approval (stored as JSON) |
| `equity_snapshots` | One equity value per day, used for the equity curve |

Short options are stored as negative quantities. One merge function (`Portfolio._merge`) then handles opening, adding to and closing both long and short positions, and calculates the realized P&L.

### Order lifecycle
```
Order ──► _fill_price()    stock: last price · option: ask (buy) / bid (sell)
      ──► _validate()      buying power · covered-call shares · CSP collateral · position direction
      ──► preview()        returns the estimated Fill (no changes made)
      ──► execute()        inside one SQLite transaction (BEGIN … COMMIT / ROLLBACK):
                             update position → update cash → append to trades
      ──► reindex_journal  trade text is re-embedded so the AI can see it
```
Expiration runs once per browser session (`process_expirations`). Each expired contract is settled in its own transaction. An assignment touches both the option and the stock position, and either both changes are saved or neither is.

### AI agent loop
```
User prompt
   │
   ▼
client.beta.messages.tool_runner(model, system, tools, messages, thinking=adaptive,
                                 effort=medium, cache_control, fallbacks="default")
   │
   ├─► Claude replies with tool_use blocks ──► Python runs the tools ──► tool_result ──┐
   │                                                                                   │
   └───────────────────────────── loops until stop_reason == end_turn ◄────────────────┘
   │
   ▼
Streamlit shows reasoning, each tool call (inputs + results), and the final answer
```
- **Typed tools:** each tool is a plain Python function with the `@beta_tool` decorator. Its JSON schema is generated from the type hints (`Literal` becomes an enum, `Optional` becomes nullable) and the docstring.
- **Error handling:** a `_safe` wrapper turns validation errors into readable tool results, so Claude can recover instead of the loop crashing.
- **Conversation history:** each assistant message and tool result is appended to the history in Streamlit session state, so multi-turn conversations keep their full context.
- **Human-in-the-loop:** `propose_trade` writes to `pending_orders`. Nothing runs until the user clicks Approve, which goes through the same `Portfolio.execute()` path as a manual trade.
- **Prompt caching:** the system prompt and tool definitions stay the same between requests, so they're cached. Volatile data such as prices only comes in through tool results.

### RAG pipeline
```
 Sources                   Ingest                         Store                     Retrieve
 ─────────                 ──────                         ─────                     ────────
 knowledge/*.md   ─┐       split by "## " sections        ChromaDB collection       query embedding
 trades + journal ─┼──►    paragraph-packing chunker ──►  cosine HNSW index    ──►  + metadata filter
 Yahoo news RSS   ─┤       (1200 chars, 200 overlap)      metadata: source,         (source ∈ [...],
 SEC 10-K / 10-Q  ─┘       title prepended to chunk       symbol, title, url,        symbol = X)
                           local MiniLM-L6-v2 embeddings  date, chunk index          → top-k + citation
```
- **Free embeddings:** they're computed on your machine (ONNX all-MiniLM-L6-v2 through Chroma), so they cost nothing and need no second API key.
- **No duplicates:** chunk IDs are `sha1(source | key | chunk_index)`, and each document's old chunks are deleted before new ones are added, so re-ingesting never creates duplicates.
- **Filing extraction:** a 10-K is hundreds of pages, so only the high-signal sections (Risk Factors, MD&A) are indexed. Section headings show up first in the table of contents, so the code uses the **longest** match between an `Item 1A`-style heading and the next item heading. That picks the real section rather than the table of contents entry.
- **Context-aware chunks:** the title is prepended to each chunk before embedding, so short chunks still match queries about their topic.

### Pricing & analytics
- **Pricing model:** Black-Scholes with a 4% risk-free rate. Expiration day counts as half a day, so Greeks don't blow up on the last day.
- **Implied volatility:** solved from the bid/ask midpoint with Brent's method, because Yahoo's IV field is unreliable outside market hours. If there's no usable quote, it falls back to 30-day realized volatility.
- **Position marks:** chain mid price when available, otherwise a Black-Scholes value.
- **Caching:** market data is cached in memory with time-to-live expiry (30 s for quotes, 2 min for chains, 1 h for history and expirations), which keeps the UI responsive and avoids Yahoo rate limits.

### Key design decisions

| Decision | Why |
|---|---|
| Streamlit over a React frontend | One language and fast iteration, with good enough charts and tables for a dashboard-style app |
| SQLite over Postgres | Single-user and zero setup. Transactions keep cash and positions consistent |
| ChromaDB + local embeddings | No extra service or API key, data stays on disk, and it supports metadata filtering |
| Bid/ask fills instead of mid | Mid-price fills make paper results look better than real trading would |
| Validate covered calls and CSP collateral | Blocks naked options, matching a typical level-2 options account |
| AI trades queued for approval by default | Safety: the AI can suggest, but only the user commits |
| Mocked API in tests | The agent loop can be tested in CI without a key, network access or cost |

### How it was built
The app was built in incremental layers. Each layer was tested before the next one was added on top:

1. **Domain core first:** the SQLite schema and `Portfolio` engine, with pytest coverage for every trading rule (covered-call checks, collateral, assignment, P&L) using a `FakeMarket` test double.
2. **Pricing math:** Black-Scholes, Greeks and the implied-vol solver, checked with put-call parity and IV round-trip tests.
3. **Market data:** a yfinance wrapper with a `MarketData` interface (a `Protocol`), so the engine can use live or fake data.
4. **RAG:** the chunker, ChromaDB store and loaders. Ingestion was checked against real Yahoo RSS and SEC EDGAR data.
5. **AI agent:** tool definitions and the tool-runner loop. It was tested end to end against a mocked HTTP transport, then verified with a live Claude call.
6. **UI:** the Streamlit pages, smoke-tested with Streamlit's `AppTest`, including a full buy-shares → sell-covered-call flow.

The development was AI-assisted, using Claude Code as a pair programmer.

---

## Tests

```bash
.venv/bin/python -m pytest
```

There are 19 tests:
- Trading rules: covered/cash-secured checks, buying power, overselling.
- P&L math, call assignment, put assignment, and worthless expiry.
- Black-Scholes: put-call parity, Greeks, and implied vol round trip.
- Strategy metrics and payoff curves.
- RAG chunking and filtered search.
- An end-to-end agent loop against a **mocked Claude API**. No key or network needed.

---

## Limitations
- Quotes are about 15 minutes delayed, and only market orders are supported (no limit orders).
- Only single-leg options are supported; no spreads.
- Long in-the-money options pay out their value in cash instead of being exercised.
- When you're assigned, the option premium counts as realized P&L instead of lowering your cost basis.
- Black-Scholes treats options as European-style, which is close enough for short-dated contracts.

## Roadmap ideas
- Multi-leg strategies (vertical spreads, iron condors, collars)
- Limit orders and a simple order book
- Backtesting the wheel strategy on historical data
- An evaluation set to measure the quality of the copilot's answers

---

*For education only. Not financial advice.*

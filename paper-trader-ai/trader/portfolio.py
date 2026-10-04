"""Paper-trading engine: order validation, fills, positions, P&L, and option expiration/assignment.

Rules (kept close to a typical cash account with level-2 options approval):
- Stocks are long-only, whole shares, filled at the last price, no commission.
- Options fill at the ask when buying and the bid when selling, plus a per-contract commission.
- Calls may only be written when covered by 100 free shares per contract (covered calls).
- Puts may only be written when cash-secured: strike x 100 per contract is reserved from buying power.
- At expiration, OTM options expire worthless. ITM short calls are assigned (shares called away at the strike),
  ITM short puts are assigned (shares bought at the strike), and ITM long options are cash-settled at intrinsic value.
"""
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date

from .config import CONTRACT_SIZE, OPTION_COMMISSION
from .db import now_iso
from .market import MarketData
from .options_math import bs_price, greeks, intrinsic, year_fraction

STOCK_ACTIONS = ("buy", "sell")
OPTION_ACTIONS = ("buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close")


class OrderError(ValueError):
    pass


@dataclass
class Order:
    asset_type: str  # "stock" | "option"
    action: str
    symbol: str
    quantity: int  # shares for stock, contracts for options
    option_type: str | None = None
    strike: float | None = None
    expiration: str | None = None  # YYYY-MM-DD
    note: str | None = None

    def __post_init__(self):
        self.symbol = self.symbol.upper().strip()
        self.quantity = int(self.quantity)
        if self.strike is not None:
            self.strike = float(self.strike)

    @property
    def side(self) -> str:
        return "buy" if self.action.startswith("buy") else "sell"

    @property
    def strategy(self) -> str | None:
        if self.asset_type != "option":
            return None
        if self.action == "sell_to_open":
            return "covered_call" if self.option_type == "call" else "cash_secured_put"
        if self.action == "buy_to_open":
            return f"long_{self.option_type}"
        return None

    def describe(self) -> str:
        if self.asset_type == "stock":
            return f"{self.action.upper()} {self.quantity} {self.symbol}"
        return (f"{self.action.replace('_', ' ').upper()} {self.quantity}x {self.symbol} "
                f"{self.expiration} {self.strike:g} {self.option_type.upper()}")


@dataclass
class Fill:
    order: Order
    price: float
    fees: float
    cash_delta: float
    trade_id: int | None = None
    realized_pnl: float = 0.0
    notes: list[str] = field(default_factory=list)


class Portfolio:
    def __init__(self, conn: sqlite3.Connection, market: MarketData, commission: float = OPTION_COMMISSION):
        self.conn = conn
        self.market = market
        self.commission = commission

    # ---------- reads ----------

    def cash(self) -> float:
        return self.conn.execute("SELECT cash FROM account").fetchone()["cash"]

    def starting_cash(self) -> float:
        return self.conn.execute("SELECT starting_cash FROM account").fetchone()["starting_cash"]

    def stocks(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM stock_positions ORDER BY symbol")]

    def options(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM option_positions ORDER BY expiration, symbol, strike")]

    def stock_qty(self, symbol: str) -> int:
        row = self.conn.execute("SELECT qty FROM stock_positions WHERE symbol = ?", (symbol.upper(),)).fetchone()
        return row["qty"] if row else 0

    def option_position(self, symbol: str, option_type: str, strike: float, expiration: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM option_positions WHERE symbol = ? AND option_type = ? AND strike = ? AND expiration = ?",
            (symbol.upper(), option_type, float(strike), expiration),
        ).fetchone()
        return dict(row) if row else None

    def short_call_contracts(self, symbol: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(-qty), 0) AS n FROM option_positions WHERE symbol = ? AND option_type = 'call' AND qty < 0",
            (symbol.upper(),),
        ).fetchone()
        return row["n"]

    def free_shares(self, symbol: str) -> int:
        """Shares not already committed as cover for short calls."""
        return self.stock_qty(symbol) - CONTRACT_SIZE * self.short_call_contracts(symbol)

    def put_collateral(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(strike * -qty), 0) AS c FROM option_positions WHERE option_type = 'put' AND qty < 0"
        ).fetchone()
        return row["c"] * CONTRACT_SIZE

    def buying_power(self) -> float:
        return self.cash() - self.put_collateral()

    def realized_pnl(self) -> float:
        return self.conn.execute("SELECT COALESCE(SUM(realized_pnl), 0) AS p FROM trades").fetchone()["p"]

    def trades(self, limit: int | None = None, symbol: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM trades", []
        if symbol:
            sql += " WHERE symbol = ?"
            args.append(symbol.upper())
        sql += " ORDER BY id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(sql, args)]

    # ---------- orders ----------

    def _fill_price(self, order: Order) -> float:
        if order.asset_type == "stock":
            return self.market.get_price(order.symbol)
        quote = self.market.get_option_quote(order.symbol, order.option_type, order.strike, order.expiration)
        if quote is None:
            raise OrderError(f"No quote found for {order.describe()}. Check the strike and expiration.")
        price = quote.fill_price(order.side)
        if price <= 0:
            raise OrderError(f"No bid/ask for {order.describe()} right now.")
        return round(price, 2)

    def _validate(self, order: Order, price: float) -> None:
        if order.quantity <= 0:
            raise OrderError("Quantity must be a positive whole number.")
        if order.asset_type == "stock":
            if order.action not in STOCK_ACTIONS:
                raise OrderError(f"Stock action must be one of {STOCK_ACTIONS}.")
            if order.action == "buy" and price * order.quantity > self.buying_power():
                raise OrderError(f"Insufficient buying power: need ${price * order.quantity:,.2f}, "
                                 f"have ${self.buying_power():,.2f}.")
            if order.action == "sell":
                free = self.free_shares(order.symbol)
                if order.quantity > free:
                    raise OrderError(f"Can only sell {max(free, 0)} {order.symbol} shares "
                                     "(the rest are held, or are covering short calls).")
            return

        if order.action not in OPTION_ACTIONS:
            raise OrderError(f"Option action must be one of {OPTION_ACTIONS}.")
        if order.option_type not in ("call", "put") or not order.strike or not order.expiration:
            raise OrderError("Options orders need option_type (call/put), strike, and expiration.")
        try:
            exp = date.fromisoformat(order.expiration)
        except ValueError:
            raise OrderError("Expiration must be YYYY-MM-DD.") from None
        if exp < date.today() and order.action.endswith("open"):
            raise OrderError("That contract has already expired.")

        n = order.quantity
        premium = price * CONTRACT_SIZE * n
        fees = self.commission * n
        pos = self.option_position(order.symbol, order.option_type, order.strike, order.expiration)
        held = pos["qty"] if pos else 0

        if order.action == "buy_to_open":
            if held < 0:
                raise OrderError("You are short this contract; use buy_to_close.")
            if premium + fees > self.buying_power():
                raise OrderError(f"Insufficient buying power: need ${premium + fees:,.2f}, "
                                 f"have ${self.buying_power():,.2f}.")
        elif order.action == "sell_to_open":
            if held > 0:
                raise OrderError("You are long this contract; use sell_to_close.")
            if order.option_type == "call":
                free = self.free_shares(order.symbol)
                if free < CONTRACT_SIZE * n:
                    raise OrderError(f"Covered calls need {CONTRACT_SIZE * n} free {order.symbol} shares; "
                                     f"you have {max(free, 0)}. Naked calls are not allowed.")
            else:
                collateral = order.strike * CONTRACT_SIZE * n
                available = self.buying_power() + premium - fees
                if collateral > available:
                    raise OrderError(f"Cash-secured put needs ${collateral:,.2f} collateral; "
                                     f"available ${available:,.2f}.")
        elif order.action == "buy_to_close":
            if held >= 0 or n > -held:
                raise OrderError(f"You are short {max(-held, 0)} of this contract.")
            if premium + fees > self.cash():
                raise OrderError("Insufficient cash to buy back this contract.")
        elif order.action == "sell_to_close":
            if held <= 0 or n > held:
                raise OrderError(f"You are long {max(held, 0)} of this contract.")

    def preview(self, order: Order) -> Fill:
        price = self._fill_price(order)
        self._validate(order, price)
        mult = 1 if order.asset_type == "stock" else CONTRACT_SIZE
        fees = 0.0 if order.asset_type == "stock" else self.commission * order.quantity
        sign = -1 if order.side == "buy" else 1
        return Fill(order, price, fees, sign * price * mult * order.quantity - fees)

    def execute(self, order: Order) -> Fill:
        fill = self.preview(order)
        with self._transaction():
            if order.asset_type == "stock":
                delta = order.quantity if order.side == "buy" else -order.quantity
                fill.trade_id, fill.realized_pnl = self._apply_stock(
                    order.symbol, delta, fill.price, order.action, note=order.note)
            else:
                delta = order.quantity if order.side == "buy" else -order.quantity
                fill.trade_id, fill.realized_pnl = self._apply_option(
                    order.symbol, order.option_type, order.strike, order.expiration, delta, fill.price,
                    order.action, fees=fill.fees, strategy=order.strategy, note=order.note)
        return fill

    # ---------- low-level position updates (call inside a transaction) ----------

    def _transaction(self):
        conn = self.conn

        class _Tx:
            def __enter__(self):
                conn.execute("BEGIN")

            def __exit__(self, exc_type, *_):
                conn.execute("ROLLBACK" if exc_type else "COMMIT")

        return _Tx()

    def _record_trade(self, asset_type, symbol, action, qty, price, cash_delta, realized, fees=0.0,
                      option_type=None, strike=None, expiration=None, strategy=None, note=None) -> int:
        self.conn.execute("UPDATE account SET cash = cash + ?", (cash_delta,))
        cur = self.conn.execute(
            """INSERT INTO trades (ts, asset_type, symbol, action, qty, price, option_type, strike, expiration,
                                   fees, cash_delta, realized_pnl, strategy, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now_iso(), asset_type, symbol, action, abs(qty), price, option_type, strike, expiration,
             fees, round(cash_delta, 2), round(realized, 2), strategy, note),
        )
        return cur.lastrowid

    @staticmethod
    def _merge(held: int, avg: float, delta: int, price: float) -> tuple[int, float, float]:
        """Apply a signed quantity change to a position. Returns (new_qty, new_avg, realized_per_unit_total)."""
        if held == 0 or (held > 0) == (delta > 0):
            new_qty = held + delta
            new_avg = (abs(held) * avg + abs(delta) * price) / abs(new_qty)
            return new_qty, new_avg, 0.0
        closed = min(abs(delta), abs(held))
        if abs(delta) > abs(held):
            raise OrderError("Order would flip the position direction.")
        realized = (price - avg) * closed * (1 if held > 0 else -1)
        return held + delta, avg, realized

    def _apply_stock(self, symbol, delta, price, action, note=None) -> tuple[int, float]:
        row = self.conn.execute("SELECT qty, avg_cost FROM stock_positions WHERE symbol = ?", (symbol,)).fetchone()
        held, avg = (row["qty"], row["avg_cost"]) if row else (0, 0.0)
        new_qty, new_avg, realized = self._merge(held, avg, delta, price)
        if new_qty == 0:
            self.conn.execute("DELETE FROM stock_positions WHERE symbol = ?", (symbol,))
        else:
            self.conn.execute(
                "INSERT INTO stock_positions (symbol, qty, avg_cost) VALUES (?, ?, ?) "
                "ON CONFLICT (symbol) DO UPDATE SET qty = excluded.qty, avg_cost = excluded.avg_cost",
                (symbol, new_qty, new_avg),
            )
        trade_id = self._record_trade("stock", symbol, action, delta, price, -delta * price, realized, note=note)
        return trade_id, realized

    @staticmethod
    def position_strategy(option_type: str, qty: int) -> str:
        if qty < 0:
            return "covered_call" if option_type == "call" else "cash_secured_put"
        return f"long_{option_type}"

    def _apply_option(self, symbol, option_type, strike, expiration, delta, price, action,
                      fees=0.0, strategy=None, note=None) -> tuple[int, float]:
        pos = self.option_position(symbol, option_type, strike, expiration)
        held, avg = (pos["qty"], pos["avg_price"]) if pos else (0, 0.0)
        strategy = strategy or self.position_strategy(option_type, held or delta)
        new_qty, new_avg, realized = self._merge(held, avg, delta, price)
        realized = realized * CONTRACT_SIZE - fees
        if new_qty == 0:
            self.conn.execute("DELETE FROM option_positions WHERE id = ?", (pos["id"],))
        elif pos:
            self.conn.execute("UPDATE option_positions SET qty = ?, avg_price = ? WHERE id = ?",
                              (new_qty, new_avg, pos["id"]))
        else:
            self.conn.execute(
                "INSERT INTO option_positions (symbol, option_type, strike, expiration, qty, avg_price, opened_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, option_type, strike, expiration, new_qty, new_avg, now_iso()),
            )
        # Opening fees aren't "realized" yet but they are a real cost; book them immediately so P&L is honest.
        cash_delta = -delta * price * CONTRACT_SIZE - fees
        trade_id = self._record_trade("option", symbol, action, delta, price, cash_delta, realized, fees=fees,
                                      option_type=option_type, strike=strike, expiration=expiration,
                                      strategy=strategy, note=note)
        return trade_id, realized

    # ---------- expiration ----------

    def process_expirations(self, today: date | None = None) -> list[str]:
        """Settle every option whose expiration date has passed. Returns human-readable events."""
        today = today or date.today()
        expired = [p for p in self.options() if date.fromisoformat(p["expiration"]) < today]
        events = []
        for p in expired:
            sym, otype, K, exp, qty = p["symbol"], p["option_type"], p["strike"], p["expiration"], p["qty"]
            S = self.market.get_close_on(sym, date.fromisoformat(exp))
            value = intrinsic(S, K, otype)
            label = f"{abs(qty)}x {sym} {exp} {K:g} {otype.upper()}"
            with self._transaction():
                if value <= 0:
                    self._apply_option(sym, otype, K, exp, -qty, 0.0, "expired_worthless",
                                       note=f"Underlying closed at {S:.2f}")
                    events.append(f"{label} expired worthless (underlying {S:.2f}).")
                elif qty > 0:
                    self._apply_option(sym, otype, K, exp, -qty, value, "expired_itm_cash_settled",
                                       note=f"Underlying closed at {S:.2f}")
                    events.append(f"Long {label} settled for ${value * CONTRACT_SIZE * qty:,.2f} intrinsic value.")
                else:
                    n = -qty
                    self._apply_option(sym, otype, K, exp, n, 0.0, "assigned",
                                       note=f"Underlying closed at {S:.2f}")
                    if otype == "call":
                        self._apply_stock(sym, -CONTRACT_SIZE * n, K, "sell (called away)",
                                          note=f"Covered call assigned at {K:g}")
                        events.append(f"Short {label} assigned: {CONTRACT_SIZE * n} shares called away at {K:g}.")
                    else:
                        self._apply_stock(sym, CONTRACT_SIZE * n, K, "buy (put assigned)",
                                          note=f"Cash-secured put assigned at {K:g}")
                        events.append(f"Short {label} assigned: bought {CONTRACT_SIZE * n} shares at {K:g}.")
        return events

    # ---------- valuation ----------

    def snapshot(self) -> dict:
        """Mark every position to market and compute account totals and Greeks."""
        stocks, options = [], []
        stock_value = option_value = net_delta = 0.0
        prices: dict[str, float] = {}

        def price_of(sym: str, fallback: float) -> float:
            if sym not in prices:
                try:
                    prices[sym] = self.market.get_price(sym)
                except Exception:
                    prices[sym] = fallback
            return prices[sym]

        for s in self.stocks():
            px = price_of(s["symbol"], s["avg_cost"])
            mv = px * s["qty"]
            stock_value += mv
            net_delta += s["qty"]
            stocks.append(s | {
                "price": round(px, 2), "market_value": round(mv, 2),
                "unrealized_pnl": round((px - s["avg_cost"]) * s["qty"], 2),
                "unrealized_pct": round((px / s["avg_cost"] - 1) * 100, 2) if s["avg_cost"] else 0.0,
                "covered_by_calls": CONTRACT_SIZE * self.short_call_contracts(s["symbol"]),
            })

        for o in self.options():
            spot = price_of(o["symbol"], o["strike"])
            exp = date.fromisoformat(o["expiration"])
            T = year_fraction(exp)
            quote = self.market.get_option_quote(o["symbol"], o["option_type"], o["strike"], o["expiration"])
            if quote:
                iv = quote.iv
            else:
                try:
                    iv = self.market.realized_vol(o["symbol"])
                except Exception:
                    iv = 0.3
            mark = quote.mid if quote and quote.mid > 0 else bs_price(spot, o["strike"], T, iv, o["option_type"])
            g = greeks(spot, o["strike"], T, iv, o["option_type"])
            units = o["qty"] * CONTRACT_SIZE
            mv = mark * units
            option_value += mv
            net_delta += g.delta * units
            options.append(o | {
                "underlying_price": round(spot, 2), "mark": round(mark, 2), "market_value": round(mv, 2),
                "unrealized_pnl": round((mark - o["avg_price"]) * units, 2),
                "dte": (exp - date.today()).days, "iv": round(iv, 4),
                "delta": round(g.delta * units, 1), "theta_per_day": round(g.theta * units, 2),
                "prob_itm": round(g.prob_itm, 3),
                "strategy": self.position_strategy(o["option_type"], o["qty"]),
            })

        cash = self.cash()
        equity = cash + stock_value + option_value
        start = self.starting_cash()
        return {
            "as_of": date.today().isoformat(),
            "cash": round(cash, 2),
            "put_collateral_reserved": round(self.put_collateral(), 2),
            "buying_power": round(self.buying_power(), 2),
            "stock_value": round(stock_value, 2),
            "option_value": round(option_value, 2),
            "equity": round(equity, 2),
            "starting_cash": start,
            "total_pnl": round(equity - start, 2),
            "total_return_pct": round((equity / start - 1) * 100, 2),
            "realized_pnl": round(self.realized_pnl(), 2),
            "net_delta_shares": round(net_delta, 1),
            "stocks": stocks,
            "options": options,
        }

    def record_equity_snapshot(self, equity: float, cash: float) -> None:
        self.conn.execute(
            "INSERT INTO equity_snapshots (date, equity, cash) VALUES (?, ?, ?) "
            "ON CONFLICT (date) DO UPDATE SET equity = excluded.equity, cash = excluded.cash",
            (date.today().isoformat(), equity, cash),
        )

    def equity_history(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM equity_snapshots ORDER BY date")]

    # ---------- pending orders (human-in-the-loop for AI proposals) ----------

    def add_pending(self, order: Order, rationale: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO pending_orders (ts, order_json, rationale) VALUES (?, ?, ?)",
            (now_iso(), json.dumps(asdict(order)), rationale),
        )
        return cur.lastrowid

    def pending(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM pending_orders WHERE status = 'pending' ORDER BY id")
        return [dict(r) | {"order": Order(**json.loads(r["order_json"]))} for r in rows]

    def resolve_pending(self, pending_id: int, approve: bool) -> Fill | None:
        row = self.conn.execute("SELECT * FROM pending_orders WHERE id = ? AND status = 'pending'",
                                (pending_id,)).fetchone()
        if row is None:
            raise OrderError("Order is no longer pending.")
        fill = None
        if approve:
            order = Order(**json.loads(row["order_json"]))
            fill = self.execute(order)
            if row["rationale"]:
                self.add_journal(f"AI-proposed trade approved: {order.describe()}. Rationale: {row['rationale']}",
                                 symbol=order.symbol, trade_id=fill.trade_id)
        self.conn.execute("UPDATE pending_orders SET status = ? WHERE id = ?",
                          ("executed" if approve else "rejected", pending_id))
        return fill

    # ---------- journal ----------

    def add_journal(self, text: str, symbol: str | None = None, trade_id: int | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO journal (ts, trade_id, symbol, text) VALUES (?, ?, ?, ?)",
            (now_iso(), trade_id, symbol.upper() if symbol else None, text),
        )
        return cur.lastrowid

    def journal(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM journal ORDER BY id DESC")]

"""Exercise the agent loop end to end against a mocked Claude API (no network or API key needed)."""
import json

import anthropic
import httpx2

from trader.agent import TradingAgent
from trader.rag import KnowledgeBase


def _message(content, stop_reason):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}


def test_tool_loop_and_trade_queueing(pf, market, expiry):
    requests = []
    replies = [
        _message([{"type": "tool_use", "id": "tu_1", "name": "get_portfolio", "input": {}},
                  {"type": "tool_use", "id": "tu_2", "name": "propose_trade",
                   "input": {"asset_type": "stock", "action": "buy", "symbol": "AAPL", "quantity": 10,
                             "rationale": "Starter position"}}], "tool_use"),
        _message([{"type": "text", "text": "Queued 10 AAPL for your approval."}], "end_turn"),
    ]

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=replies[len(requests) - 1])

    client = anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    agent = TradingAgent(pf, market, KnowledgeBase(collection="agent_test"), client=client)
    messages = [{"role": "user", "content": "Buy me 10 AAPL"}]
    out = list(agent.run(messages))

    assert out[-1].content[0].text.startswith("Queued")
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    results = {r["tool_use_id"]: r["content"] for r in messages[2]["content"]}
    assert json.loads(results["tu_1"])["cash"] == 100_000
    assert json.loads(results["tu_2"])["status"] == "queued_for_user_approval"
    assert len(pf.pending()) == 1 and pf.stock_qty("AAPL") == 0  # nothing executes without approval

    body = requests[0]
    assert body["model"] == "claude-opus-5-5"
    assert body["thinking"]["type"] == "adaptive"
    assert body["fallbacks"] == "default"
    assert {t["name"] for t in body["tools"]} >= {"get_portfolio", "search_knowledge", "propose_trade"}

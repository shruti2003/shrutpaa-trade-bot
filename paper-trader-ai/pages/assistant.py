import json

import anthropic
import streamlit as st

from trader import services
from trader.agent import TradingAgent
from trader.ui import render_pending_orders

pf = services.portfolio()
st.title("AI copilot")
st.caption("Claude with tool use over your paper portfolio, live quotes and option chains, plus RAG over strategy "
           "guides, your trade journal, news and SEC filings.")

with st.sidebar:
    st.markdown("### Copilot settings")
    auto = st.toggle("Let the AI execute trades without approval", value=False,
                     help="Off: AI trade ideas are queued below for you to approve or reject.")
    if st.button("Clear conversation"):
        st.session_state.pop("chat_api", None)
        st.session_state.pop("chat_display", None)
        st.rerun()

api_messages: list = st.session_state.setdefault("chat_api", [])
display: list = st.session_state.setdefault("chat_display", [])


def render_parts(parts: list) -> None:
    for kind, *payload in parts:
        if kind == "thinking" and payload[0].strip():
            with st.expander("Reasoning", icon=":material/psychology:"):
                st.markdown(payload[0])
        elif kind == "tool":
            name, args, result = payload
            with st.status(f"`{name}`", state="complete", expanded=False):
                st.code(json.dumps(args, indent=2), language="json")
                if result:
                    st.caption("Result")
                    st.code(result[:3000] + ("..." if len(result) > 3000 else ""), language="json")
        elif kind == "text":
            st.markdown(payload[0])
        elif kind == "notice":
            st.caption(payload[0])


for entry in display:
    with st.chat_message(entry["role"]):
        render_parts(entry["parts"])

SUGGESTIONS = {  # short button label -> full prompt sent to the copilot
    "Portfolio risks": "Review my portfolio and tell me my biggest risks.",
    "Covered call idea": "Find me a ~30 day covered call on shares I own.",
    "Compare AAPL puts": "I want to own AAPL cheaper. Compare 3 cash-secured put strikes for next month.",
    "NVDA news & 10-K": "What does the latest news and 10-K say about NVDA's risks?",
    "Journal patterns": "Look through my journal: what patterns do you see in my winning vs losing trades?",
}
prompt = st.chat_input("Ask about your portfolio, a strategy, or a ticker...")
if not display:
    st.caption("Try one:")
    cols = st.columns(len(SUGGESTIONS))
    for col, (label, full) in zip(cols, SUGGESTIONS.items()):
        if col.button(label, help=full, width="stretch"):
            prompt = full

if prompt:
    display.append({"role": "user", "parts": [("text", prompt)]})
    api_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    agent = TradingAgent(pf, services.market(), services.kb(), auto_execute=auto)
    parts: list = []
    with st.chat_message("assistant"):
        try:
            with st.spinner("Thinking..."):
                for message in agent.run(api_messages):
                    results = {}
                    last = api_messages[-1]
                    if last["role"] == "user" and isinstance(last["content"], list):
                        for r in last["content"]:
                            content = r.get("content")
                            results[r.get("tool_use_id")] = content if isinstance(content, str) else json.dumps(content, default=str)
                    new_parts = []
                    for block in message.content:
                        if block.type == "thinking":
                            new_parts.append(("thinking", block.thinking))
                        elif block.type == "text":
                            new_parts.append(("text", block.text))
                        elif block.type == "tool_use":
                            new_parts.append(("tool", block.name, block.input, results.get(block.id, "")))
                        elif block.type == "fallback":
                            new_parts.append(("notice", f"Answered by fallback model {block.to.model}."))
                    if message.stop_reason == "refusal":
                        new_parts.append(("notice", "The model declined this request. Try rephrasing."))
                    render_parts(new_parts)
                    parts.extend(new_parts)
        except anthropic.AuthenticationError:
            st.error("No valid Anthropic credentials. Set ANTHROPIC_API_KEY (or run `ant auth login`) and restart.")
        except anthropic.RateLimitError:
            st.error("Rate limited by the Claude API. Wait a moment and try again.")
        except anthropic.APIStatusError as e:
            st.error(f"Claude API error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError:
            st.error("Couldn't reach the Claude API. Check your network connection.")
    display.append({"role": "assistant", "parts": parts})
    if pf.pending():
        st.rerun()

render_pending_orders(pf, "chat")

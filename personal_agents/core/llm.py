from __future__ import annotations

import os

import anthropic

from .agent import BaseAgent

# Default to the most capable model; override per-run with $AGENTS_MODEL or --model.
DEFAULT_MODEL = os.environ.get("AGENTS_MODEL", "claude-opus-4-8")
MAX_TOKENS = 16000


class AgentRunner:
    """Drives the tool-use conversation loop for a single agent.

    Holds the running message history for the session. The agent's durable
    memory lives on disk (via its tools); this history is just the live chat.
    """

    def __init__(self, agent: BaseAgent, model: str = DEFAULT_MODEL, client=None):
        self.agent = agent
        self.model = model
        # Inject a client for testing; otherwise read creds from the environment.
        self.client = client if client is not None else anthropic.Anthropic()
        tools = agent.tools()
        self._tools = {t.name: t for t in tools}
        self._schemas = [t.schema() for t in tools]
        self.messages: list = []

    def send(self, user_message: str) -> str:
        """Send one user turn; run tools until the model is done; return its reply."""
        self.messages.append({"role": "user", "content": user_message})
        while True:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.agent.system_prompt(),
                thinking={"type": "adaptive"},
                tools=self._schemas,
                messages=self.messages,
            )
            # Append the full content (incl. thinking/tool_use blocks) verbatim.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                results = []
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self._dispatch(block.name, block.input),
                        })
                self.messages.append({"role": "user", "content": results})
                continue

            return self._final_text(response)

    def _dispatch(self, name: str, tool_input: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool {name!r}"
        try:
            return tool.handler(tool_input or {})
        except Exception as e:  # surface tool errors so the model can recover/ask
            return f"Error: {e}"

    @staticmethod
    def _final_text(response) -> str:
        text = "\n".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ).strip()
        if getattr(response, "stop_reason", None) == "refusal":
            return text or "[The assistant declined to respond to that request.]"
        return text or "[No textual response.]"

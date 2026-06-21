from __future__ import annotations

import json
import logging
import os
import time

import anthropic

# The google-genai SDK logs a WARNING when google_search and function_declarations
# are mixed (it disables Automatic Function Calling). We run our own tool loop so
# AFC is irrelevant — silence that logger to keep output clean.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

from .agent import BaseAgent

# Default to the most capable model; override per-run with $AGENTS_MODEL or --model.
DEFAULT_MODEL = os.environ.get("AGENTS_MODEL", "claude-opus-4-8")
MAX_TOKENS = 16000


def _is_gemini(model: str) -> bool:
    return model.startswith("gemini-")


def _is_deepseek(model: str) -> bool:
    return model.startswith("deepseek-")


class _AnthropicRunner:
    """Anthropic-backed tool-use loop."""

    def __init__(self, agent: BaseAgent, model: str, client=None):
        self.agent = agent
        self.model = model
        self.client = client if client is not None else anthropic.Anthropic()
        tools = agent.tools()
        self._tools = {t.name: t for t in tools}
        self._schemas = [t.schema() for t in tools]
        self.messages: list = []

    def send(self, user_message: str) -> str:
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
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _final_text(response) -> str:
        text = "\n".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ).strip()
        if getattr(response, "stop_reason", None) == "refusal":
            return text or "[The assistant declined to respond to that request.]"
        return text or "[No textual response.]"


class _OpenAICompatRunner:
    """OpenAI-compatible tool-use loop (DeepSeek, Ollama, etc.)."""

    # Provider routing: model prefix → (base_url, api_key_env)
    _PROVIDERS = {
        "deepseek-": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    }

    def __init__(self, agent: BaseAgent, model: str, client=None):
        import openai

        self.agent = agent
        self.model = model
        tools = agent.tools()
        self._tools = {t.name: t for t in tools}
        # OpenAI tool schema: {"type": "function", "function": {"name", "description", "parameters"}}
        self._schemas = [
            {
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["input_schema"],
                },
            }
            for t in tools
            for s in [t.schema()]
        ]
        self.messages: list = []

        if client is not None:
            self._client = client
        else:
            base_url, key_env = next(
                (cfg for prefix, cfg in self._PROVIDERS.items() if model.startswith(prefix)),
                ("https://api.openai.com/v1", "OPENAI_API_KEY"),
            )
            self._client = openai.OpenAI(
                api_key=os.environ.get(key_env, ""),
                base_url=base_url,
            )

    def _call_with_retry(self, max_attempts: int = 6, **kwargs):
        import openai
        delay = 15
        for attempt in range(max_attempts):
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.RateLimitError:
                if attempt < max_attempts - 1:
                    print(f"\n⏳  Rate limited — retrying in {delay}s…", flush=True)
                    time.sleep(delay)
                    delay = min(delay * 2, 120)
                else:
                    raise

    def send(self, user_message: str) -> str:
        self.messages.append({"role": "user", "content": user_message})

        while True:
            # System prompt prepended fresh each call so live memory changes are picked up.
            full_messages = [
                {"role": "system", "content": self.agent.system_prompt()}
            ] + self.messages

            response = self._call_with_retry(
                model=self.model,
                messages=full_messages,
                tools=self._schemas,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            # Store as plain dict so serialisation is consistent.
            assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            self.messages.append(assistant_entry)

            if not msg.tool_calls:
                return msg.content or "[No textual response.]"

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = self._dispatch(tc.function.name, args)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

    def _dispatch(self, name: str, tool_input: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool {name!r}"
        try:
            return tool.handler(tool_input or {})
        except Exception as e:
            return f"Error: {e}"


class _GeminiRunner:
    """Google Gemini-backed tool-use loop via the google-genai SDK."""

    def __init__(self, agent: BaseAgent, model: str, client=None):
        from google import genai
        from google.genai import types as gtypes

        self._gtypes = gtypes
        self._tools_map = {t.name: t for t in agent.tools()}

        fn_decls = []
        for t in agent.tools():
            s = t.schema()
            fn_decls.append(gtypes.FunctionDeclaration(
                name=s["name"],
                description=s["description"],
                parameters=_GeminiRunner._to_gemini_schema(s["input_schema"]),
            ))

        # google_search runs server-side; the model uses it transparently
        # alongside our custom function tools (no extra API key needed).
        gemini_tools = [gtypes.Tool(google_search=gtypes.GoogleSearch())]
        if fn_decls:
            gemini_tools.append(gtypes.Tool(function_declarations=fn_decls))

        self._client = client if client is not None else genai.Client(
            api_key=os.environ.get("GOOGLE_API_KEY", ""),
        )
        self._chat = self._client.chats.create(
            model=model,
            config=gtypes.GenerateContentConfig(
                system_instruction=agent.system_prompt(),
                tools=gemini_tools,
            ),
        )

    @staticmethod
    def _to_gemini_schema(schema: dict) -> dict:
        """Recursively uppercase JSON Schema type strings for Gemini's Schema format."""
        if not isinstance(schema, dict):
            return schema
        out = {}
        for k, v in schema.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.upper()
            elif isinstance(v, dict):
                out[k] = _GeminiRunner._to_gemini_schema(v)
            elif isinstance(v, list):
                out[k] = [
                    _GeminiRunner._to_gemini_schema(i) if isinstance(i, dict) else i
                    for i in v
                ]
            else:
                out[k] = v
        return out

    def _send_with_retry(self, message, max_attempts: int = 6) -> object:
        from google.genai import errors as genai_errors
        delay = 15
        for attempt in range(max_attempts):
            try:
                return self._chat.send_message(message)
            except genai_errors.ClientError as e:
                if "429" in str(e) and attempt < max_attempts - 1:
                    print(f"\n⏳  Rate limited — retrying in {delay}s…", flush=True)
                    time.sleep(delay)
                    delay = min(delay * 2, 120)
                else:
                    raise

    def send(self, user_message: str) -> str:
        gtypes = self._gtypes
        response = self._send_with_retry(user_message)

        while True:
            fn_calls = [
                p.function_call
                for p in response.candidates[0].content.parts
                if p.function_call is not None
            ]
            if not fn_calls:
                break

            result_parts = []
            for fc in fn_calls:
                result = self._dispatch(fc.name, dict(fc.args))
                result_parts.append(gtypes.Part(
                    function_response=gtypes.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                ))
            response = self._send_with_retry(result_parts)

        return self._final_text(response)

    def _dispatch(self, name: str, tool_input: dict) -> str:
        tool = self._tools_map.get(name)
        if tool is None:
            return f"Error: unknown tool {name!r}"
        try:
            return tool.handler(tool_input or {})
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _final_text(response) -> str:
        parts = response.candidates[0].content.parts
        return "\n".join(
            p.text for p in parts if getattr(p, "text", None)
        ).strip() or "[No textual response.]"


class AgentRunner:
    """Routes to Anthropic, Gemini, or OpenAI-compat backend by model name prefix."""

    def __init__(self, agent: BaseAgent, model: str = DEFAULT_MODEL, client=None):
        self.agent = agent
        self.model = model
        if _is_gemini(model):
            self._backend: _AnthropicRunner | _GeminiRunner | _OpenAICompatRunner = (
                _GeminiRunner(agent, model, client)
            )
        elif _is_deepseek(model):
            self._backend = _OpenAICompatRunner(agent, model, client)
        else:
            self._backend = _AnthropicRunner(agent, model, client)

    @property
    def messages(self) -> list:
        return getattr(self._backend, "messages", [])

    def send(self, user_message: str) -> str:
        """Send one user turn; run tools until the model is done; return its reply."""
        return self._backend.send(user_message)

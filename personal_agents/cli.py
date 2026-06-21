from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Load a local .env if python-dotenv is available (optional convenience).
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001 - dotenv is optional
    pass

from .core.llm import DEFAULT_MODEL, AgentRunner, _is_gemini, _is_deepseek
from .core.registry import discover


def _default_data_dir() -> Path:
    env = os.environ.get("AGENTS_DATA_DIR")
    return Path(env).expanduser() if env else Path.home() / ".personal_agents"


def _print_agents(agents) -> None:
    if not agents:
        print("No agents found.")
        return
    print("Available agents:")
    for name, cls in sorted(agents.items()):
        print(f"  {name:<12} {getattr(cls, 'description', '')}")


def _handle_error(e: Exception) -> None:
    import anthropic

    if isinstance(e, anthropic.AuthenticationError):
        print(
            "Authentication failed. Set ANTHROPIC_API_KEY (see README / .env.example).",
            file=sys.stderr,
        )
    elif isinstance(e, anthropic.APIConnectionError):
        print("Network error reaching the Anthropic API. Check your connection.", file=sys.stderr)
    elif isinstance(e, anthropic.APIStatusError):
        print(f"API error {e.status_code}: {getattr(e, 'message', str(e))}", file=sys.stderr)
    else:
        try:
            from google.genai import errors as genai_errors
            if isinstance(e, genai_errors.ClientError) and "429" in str(e):
                print(
                    "Google API quota exceeded (free tier: ~15 req/min). "
                    "Wait ~60 s and try again.",
                    file=sys.stderr,
                )
                return
            if isinstance(e, genai_errors.APIError):
                print(f"Google API error: {e}", file=sys.stderr)
                return
        except ImportError:
            pass
        try:
            import openai
            if isinstance(e, openai.AuthenticationError):
                print("DeepSeek authentication failed. Check DEEPSEEK_API_KEY.", file=sys.stderr)
                return
            if isinstance(e, openai.RateLimitError):
                print("DeepSeek rate limit hit. Wait a moment and try again.", file=sys.stderr)
                return
            if isinstance(e, openai.APIError):
                print(f"DeepSeek API error: {e}", file=sys.stderr)
                return
        except ImportError:
            pass
        print(f"Error: {e}", file=sys.stderr)


def _one_shot(runner: AgentRunner, message: str) -> int:
    try:
        print(runner.send(message))
        return 0
    except Exception as e:  # noqa: BLE001
        _handle_error(e)
        return 1


def _repl(runner: AgentRunner, agent) -> int:
    print(f"\N{SPEECH BALLOON}  {agent.name} agent — {agent.description}")
    print("Type a message. 'exit' or 'quit' to leave; Ctrl-D also works.\n")
    while True:
        try:
            user = input("you \N{BLACK RIGHT-POINTING SMALL TRIANGLE} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye \N{WAVING HAND SIGN}")
            return 0
        if not user:
            continue
        if user.lower() in {"exit", "quit", ":q"}:
            print("bye \N{WAVING HAND SIGN}")
            return 0
        try:
            reply = runner.send(user)
            print(f"\n{agent.name} \N{BLACK RIGHT-POINTING SMALL TRIANGLE} {reply}\n")
        except Exception as e:  # noqa: BLE001 - keep the session alive on transient errors
            _handle_error(e)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="personal_agents",
        description="A growable system of specialized, memory-keeping CLI agents.",
    )
    parser.add_argument("agent", nargs="?", help="agent to talk to, e.g. 'housing'")
    parser.add_argument(
        "message", nargs="*", help="optional one-off message; omit for an interactive chat"
    )
    parser.add_argument("--list", action="store_true", help="list available agents and exit")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="directory for agent memory (default: ~/.personal_agents or $AGENTS_DATA_DIR)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            f"model to use (default: {DEFAULT_MODEL} or $AGENTS_MODEL); "
            "e.g. claude-haiku-4-5, gemini-3.5-flash"
        ),
    )
    args = parser.parse_args(argv)

    agents = discover()

    if args.list or not args.agent:
        _print_agents(agents)
        if not args.agent:
            print(
                "\nUsage:\n"
                "  personal_agents <agent>             # interactive chat\n"
                '  personal_agents <agent> "message"   # one-off message\n'
                "  personal_agents --list"
            )
        return 0

    if args.agent not in agents:
        print(f"Unknown agent: {args.agent!r}\n", file=sys.stderr)
        _print_agents(agents)
        return 1

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else _default_data_dir()
    agent = agents[args.agent](data_dir)
    runner = AgentRunner(agent, model=args.model or DEFAULT_MODEL)

    _model = args.model or DEFAULT_MODEL
    if _is_gemini(_model):
        if not os.environ.get("GOOGLE_API_KEY"):
            print(
                "\N{WARNING SIGN}  No GOOGLE_API_KEY found. Set it in your environment or a "
                ".env file (see .env.example).",
                file=sys.stderr,
            )
    elif _is_deepseek(_model):
        if not os.environ.get("DEEPSEEK_API_KEY"):
            print(
                "\N{WARNING SIGN}  No DEEPSEEK_API_KEY found. Set it in your environment or a "
                ".env file (see .env.example).",
                file=sys.stderr,
            )
    elif not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "\N{WARNING SIGN}  No ANTHROPIC_API_KEY found. Set it in your environment or a "
            ".env file (see .env.example).",
            file=sys.stderr,
        )

    if args.message:
        return _one_shot(runner, " ".join(args.message))
    return _repl(runner, agent)

# Personal Agents

A growable system of **specialized, memory-keeping CLI agents**, powered by Claude.

Instead of one do-everything assistant, each agent owns one part of your life,
remembers what's relevant to it, and exposes a small set of tools for managing
that memory. The first agent is a **housing-search agent**. Adding the next one
is dropping a folder into `personal_agents/agents/` — no changes to the core or
to any existing agent.

---

## How it works

- **Conversational + tool-using.** You talk to an agent in plain language. Under
  the hood, Claude calls the agent's tools to record and look things up, and
  reasons over what it finds.
- **Memory is data, not chat history.** Each agent has its own directory of
  human-readable JSON. A new chat session starts cold, but the agent reloads its
  standing knowledge (and everything you've told it) every time.
- **The core never changes as you grow.** Agents self-register; the CLI discovers
  them automatically.

```
personal_agents/
├── cli.py                 # argument parsing + interactive REPL
├── core/
│   ├── agent.py           # BaseAgent + Tool + auto-registration
│   ├── registry.py        # discovers agents under agents/
│   ├── llm.py             # the Claude tool-use loop
│   └── storage.py         # atomic JSON persistence
└── agents/
    └── housing/           # the first specialized agent
        └── agent.py
tests/test_agents.py       # offline tests (data layer, registry, mocked loop)
```

---

## Requirements

- Python 3.10+
- An Anthropic API key

## Setup

```bash
# from the project root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # or: pip install -e .

cp .env.example .env                 # then put your key in .env
# or: export ANTHROPIC_API_KEY=sk-ant-...
```

## Run

If you installed with `pip install -e .`, use the `agents` command. Otherwise use
`python -m personal_agents` (identical behaviour). Examples below show both.

```bash
# List the agents you have
python -m personal_agents --list
agents --list

# Chat with the housing agent (interactive)
python -m personal_agents housing
agents housing

# Or send a single message (handy for scripting)
agents housing "I'm looking at 12 Marion Ave, $1500, basement, self-contained, 8 min walk to campus"
```

### A housing session might look like

```
you ▸ Found a basement unit at 12 Marion Ave, Westdale — $1500, own entrance/kitchen/bath, 8 min walk to campus
housing ▸ Recorded that as listing #1 (status: new). It ticks every hard requirement —
          self-contained basement, in Westdale, an 8-minute walk to McMaster.

you ▸ Also 40 Whitton Rd, $1350, but it's a shared kitchen
housing ▸ Saved as #2 (status: new). Heads up: a shared kitchen fails your
          "self-contained" requirement — want me to flag or reject it?

you ▸ yeah reject it, shared kitchen is a dealbreaker
housing ▸ Rejected #2 — reason: shared kitchen (not self-contained). I won't
          suggest it again.

you ▸ I emailed the landlord for #1
housing ▸ Updated #1 to "contacted".

you ▸ what's still in play, and how do they compare?
housing ▸ One listing in play: #1, 12 Marion Ave ($1500). It meets all your
          criteria — self-contained basement, Westdale, 8-min walk. #2 is out
          (shared kitchen). Nothing else recorded yet.
```

The housing agent already knows your situation (moving to Hamilton in September
2026 for a PhD at McMaster; basement apartment in Westdale; self-contained;
walkable/short commute), so you never restate it.

### Where memory lives

By default, under `~/.personal_agents/<agent>/`. For the housing agent:

- `profile.json` — standing criteria + any preferences you've added ("remember my
  budget cap is $1600").
- `listings.json` — every listing with its status, history, and (for rejected
  ones) the reason.

Point this somewhere else with `--data-dir ./data` or `AGENTS_DATA_DIR=./data`.

### Choosing a model

Defaults to `claude-opus-4-8`. Override per run with `--model`, or globally with
`AGENTS_MODEL` (e.g. `claude-sonnet-4-6` or `claude-haiku-4-5` to cut cost).

---

## Adding another specialized agent later

This is the whole point of the design. Say you want a `finance` agent.

**1.** Create `personal_agents/agents/finance/__init__.py`:

```python
from .agent import FinanceAgent
__all__ = ["FinanceAgent"]
```

**2.** Create `personal_agents/agents/finance/agent.py`:

```python
from __future__ import annotations
import json
from ...core.agent import BaseAgent, Tool
from ...core.storage import JsonStore


class FinanceAgent(BaseAgent):
    name = "finance"                       # the CLI name; also auto-registers it
    description = "Tracks expenses and budgets."

    def setup(self) -> None:               # runs on construction
        self.db = JsonStore(self.data_dir / "expenses.json")

    def system_prompt(self) -> str:
        return "You are the user's personal finance assistant. ..."

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="add_expense",
                description="Record an expense.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "category": {"type": "string"},
                    },
                    "required": ["amount"],
                },
                handler=self._add_expense,
            ),
        ]

    def _add_expense(self, inp: dict) -> str:
        data = self.db.load({"expenses": []})
        data["expenses"].append(inp)
        self.db.save(data)
        return f"Recorded: {json.dumps(inp)}"
```

**3.** That's it:

```bash
python -m personal_agents --list      # finance now appears
python -m personal_agents finance     # chat with it
```

No edits to `core/`, to `cli.py`, or to the housing agent. The contract is just:
subclass `BaseAgent`, set a `name`, implement `system_prompt()` and `tools()`.

### What the contract gives you

- `self.data_dir` — a private directory for your agent's memory (created for you).
- `setup()` — optional hook to open stores / seed initial data.
- `JsonStore` — atomic, human-readable JSON persistence.
- `Tool(name, description, input_schema, handler)` — `handler(input: dict) -> str`.
  Raise on bad input; the runner reports the error back to the model so it can
  recover or ask the user. The model only ever sees what your tools return.

---

## Testing

The data layer, the registry, and the full tool-use loop (with a mocked model)
are covered by offline tests — no API key or network needed:

```bash
python tests/test_agents.py     # self-contained runner
# or, if you have pytest:
pytest -q
```

A live end-to-end chat naturally requires `ANTHROPIC_API_KEY`.

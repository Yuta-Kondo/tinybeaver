"""Offline tests: data layer, registry, seeding, and the tool-use loop (mocked LLM).

Run directly (no pytest needed):  python tests/test_agents.py
Or with pytest:                   pytest -q
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Make 'personal_agents' importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from personal_agents.core.llm import AgentRunner  # noqa: E402
from personal_agents.core.registry import discover  # noqa: E402
from personal_agents.agents.housing.agent import HousingAgent  # noqa: E402


# --- a fake Claude client so we can exercise the loop with no network/key ---
class _Block:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input
        self.id = id


class _Resp:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._script.pop(0)


class FakeClient:
    def __init__(self, script):
        self.messages = _Messages(script)


def _agent(tmp) -> HousingAgent:
    return HousingAgent(Path(tmp))


# --- tests -----------------------------------------------------------------
def test_seeding_and_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        a = _agent(tmp)
        assert (a.data_dir / "profile.json").exists()
        sp = a.system_prompt()
        for token in ("McMaster", "basement", "Westdale", "September 2026"):
            assert token in sp, f"expected {token!r} in the pre-seeded system prompt"


def test_add_update_reject_flow():
    with tempfile.TemporaryDirectory() as tmp:
        s = _agent(tmp).listings
        listing = s.add({
            "address": "1 King St W", "price": 1500,
            "self_contained": True, "basement": True, "neighbourhood": "Westdale",
        })
        assert listing["id"] == "1" and listing["status"] == "new"

        s.update("1", {"status": "contacted"})
        assert s.get("1")["status"] == "contacted"

        # Rejecting without a reason must fail (rule enforced at the data layer).
        try:
            s.update("1", {"status": "rejected"})
            assert False, "expected rejection without a reason to raise"
        except ValueError:
            pass

        # Rejecting with a reason works and captures the why.
        s.update("1", {"status": "rejected", "rejection_reason": "too far from campus"})
        assert s.get("1")["status"] == "rejected"
        assert s.get("1")["rejection_reason"] == "too far from campus"


def test_list_excludes_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        s = _agent(tmp).listings
        s.add({"address": "A"})
        s.add({"address": "B"})
        s.update("2", {"status": "rejected", "rejection_reason": "no private kitchen"})
        assert {l["address"] for l in s.list()} == {"A"}
        assert len(s.list(include_rejected=True)) == 2


def test_remember_preference_shows_up_in_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        a = _agent(tmp)
        a._remember_preference({"note": "budget cap is $1600/month"})
        assert "budget cap is $1600/month" in a.system_prompt()


def test_registry_discovers_housing():
    agents = discover()
    assert "housing" in agents
    assert agents["housing"] is HousingAgent


def test_runner_tool_loop_persists_and_replies():
    with tempfile.TemporaryDirectory() as tmp:
        a = _agent(tmp)
        script = [
            _Resp(
                [
                    _Block("text", text="Saving that for you."),
                    _Block(
                        "tool_use", name="add_listing", id="t1",
                        input={"address": "5 Marion Ave", "price": 1450,
                               "self_contained": True, "basement": True},
                    ),
                ],
                stop_reason="tool_use",
            ),
            _Resp([_Block("text", text="Done — recorded 5 Marion Ave as #1.")], stop_reason="end_turn"),
        ]
        runner = AgentRunner(a, client=FakeClient(script))
        reply = runner.send("Found a place at 5 Marion Ave, $1450, basement, self-contained")

        assert "Marion" in reply
        # The tool actually ran and persisted the listing.
        assert a.listings.get("1")["address"] == "5 Marion Ave"
        # The loop threaded a tool_result back to the model.
        assert any(
            isinstance(m["content"], list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
            for m in runner.messages
        )


_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def _run() -> int:
    failed = 0
    for t in _TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(_TESTS) - failed}/{len(_TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())

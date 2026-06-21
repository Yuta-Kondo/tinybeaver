from __future__ import annotations

import importlib
import pkgutil
import sys

from . import agent as _agent_mod


def discover() -> dict[str, type[_agent_mod.BaseAgent]]:
    """Import every agent package so it self-registers, then return the registry.

    Walks ``personal_agents.agents`` and imports each submodule/subpackage. A
    broken agent logs a warning instead of taking the whole CLI down.
    """
    import personal_agents.agents as agents_pkg

    for info in pkgutil.iter_modules(agents_pkg.__path__, agents_pkg.__name__ + "."):
        try:
            importlib.import_module(info.name)
        except Exception as e:  # one bad agent shouldn't break the rest
            print(f"warning: could not load agent module {info.name!r}: {e}", file=sys.stderr)
    return _agent_mod.all_agents()

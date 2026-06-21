from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Tool:
    """One capability an agent exposes to the model.

    ``handler`` receives the model's tool input (a dict) and returns a string
    that is fed back as the tool result. Keep handlers pure-ish and total:
    raise on bad input and the runner will surface the error to the model.
    """

    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], str]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# Agents register here the moment their module is imported (see __init_subclass__).
_REGISTRY: dict[str, type["BaseAgent"]] = {}


def all_agents() -> dict[str, type["BaseAgent"]]:
    return dict(_REGISTRY)


class BaseAgent(ABC):
    """Base class for every specialized agent.

    Subclass it, set ``name``/``description``, and implement ``system_prompt``
    and ``tools``. Setting ``name`` auto-registers the agent — no central list
    to edit, so adding an agent never touches existing code.
    """

    name: str = ""
    description: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if getattr(cls, "name", ""):
            _REGISTRY[cls.name] = cls

    def __init__(self, data_dir: Path):
        # Each agent gets its own private directory for its memory.
        self.data_dir = Path(data_dir) / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.setup()

    def setup(self) -> None:
        """Optional hook: open stores / seed initial data. Runs on construction."""

    @abstractmethod
    def system_prompt(self) -> str:
        """The agent's persona + everything it already knows (its standing memory)."""

    @abstractmethod
    def tools(self) -> list[Tool]:
        """The tools the model may call to read and update this agent's memory."""

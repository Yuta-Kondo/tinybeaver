"""A growable system of specialized, memory-keeping CLI agents.

Each agent owns one part of your life and remembers what's relevant to it.
The core (agent base class, tool abstraction, discovery, LLM loop, storage)
stays fixed; new agents are added as self-contained packages under
``personal_agents/agents/`` and register themselves automatically.
"""

__version__ = "0.1.0"

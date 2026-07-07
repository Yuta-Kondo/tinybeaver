from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GEMINI = "gemini"
PROVIDER_GLM = "glm"


# ---------------------------------------------------------------------------
# Model registry — the single source of truth for all model metadata.
# To add a model: add one entry here and one in frontend/src/lib/models.ts.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    """Metadata + pricing for a selectable chat model."""
    id: str
    name: str               # short display name, e.g. "Sonnet"
    version: str            # e.g. "5"
    provider: str           # one of PROVIDER_*
    desc: str               # one-line description for the picker UI
    # Returns (input_per_million, output_per_million) in USD.
    # A callable allows time-based pricing (e.g. introductory rates).
    pricing: Callable[[], tuple[float, float]]


_SONNET5_INTRO_END = _dt.date(2026, 8, 31)


def _sonnet5_pricing() -> tuple[float, float]:
    """Sonnet 5 introductory pricing until Aug 31 2026, standard after."""
    if _dt.date.today() <= _SONNET5_INTRO_END:
        return (2.00, 10.00)
    return (3.00, 15.00)


MODELS: dict[str, ModelConfig] = {
    "claude-haiku-4-5-20251001": ModelConfig(
        id="claude-haiku-4-5-20251001",
        name="Haiku", version="4.5",
        provider=PROVIDER_ANTHROPIC, desc="Fast & efficient",
        pricing=lambda: (1.00, 5.00),
    ),
    "claude-sonnet-4-6": ModelConfig(
        id="claude-sonnet-4-6",
        name="Sonnet", version="4.6",
        provider=PROVIDER_ANTHROPIC, desc="Balanced",
        pricing=lambda: (3.00, 15.00),
    ),
    "claude-sonnet-5": ModelConfig(
        id="claude-sonnet-5",
        name="Sonnet", version="5",
        provider=PROVIDER_ANTHROPIC, desc="Recommended",
        pricing=_sonnet5_pricing,
    ),
    "claude-opus-4-8": ModelConfig(
        id="claude-opus-4-8",
        name="Opus", version="4.8",
        provider=PROVIDER_ANTHROPIC, desc="Most capable",
        pricing=lambda: (5.00, 25.00),
    ),
    "gemini-3.5-flash": ModelConfig(
        id="gemini-3.5-flash",
        name="Flash", version="3.5",
        provider=PROVIDER_GEMINI, desc="Google · Fast",
        pricing=lambda: (1.50, 9.00),
    ),
    "glm-5.2": ModelConfig(
        id="glm-5.2",
        name="GLM", version="5.2",
        provider=PROVIDER_GLM, desc="Zhipu · Open weight",
        pricing=lambda: (0.50, 2.00),
    ),
}

# Derived allow-list for validation (backward compat).
ALLOWED_MODELS: set[str] = set(MODELS.keys())

DEFAULT_MODEL = "claude-sonnet-5"

# Model used for background/utility LLM calls (classification, summarization,
# PDF cleaning, scheduled tasks, reflection). Centralized here so changing it
# only requires editing one line.
UTILITY_MODEL = "claude-haiku-4-5-20251001"

# Vision + document extraction for attachments (Gemini native multimodal).
FILE_EXTRACTION_MODEL = "gemini-3.5-flash"

# Multi-agent (MoA) pipeline — keep in sync with frontend/src/lib/models.ts MOA_*.
MOA_SYNTHESIS_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class MoAAgentDef:
    persona: str
    model: str
    provider: str
    temperature: float
    instruction: str


MOA_AGENTS: tuple[MoAAgentDef, ...] = (
    MoAAgentDef(
        "Advocate",
        "gemini-3.5-flash",
        PROVIDER_GEMINI,
        0.8,
        "Give your best recommendation: what should Yuta do and why? Cover relevant context "
        "and tradeoffs, then state a clear top recommendation.",
    ),
    MoAAgentDef(
        "Skeptic",
        "glm-5.2",
        PROVIDER_GLM,
        1.0,
        "Stress-test the Advocate's recommendation. Identify wrong assumptions, risks, failure "
        "modes, and overlooked alternatives. If the recommendation is flawed, argue for a "
        "different approach — do not merely add caveats. If you agree on the conclusion, you "
        "must still surface at least one non-obvious risk or alternative they underweighted.",
    ),
    MoAAgentDef(
        "Minimalist",
        UTILITY_MODEL,
        PROVIDER_ANTHROPIC,
        0.7,
        "Given the debate above, what is the smallest concrete action Yuta can take this week "
        "that moves the needle? What can be deferred or skipped? Push back on over-planning.",
    ),
)


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from token counts and the model's pricing."""
    config = MODELS.get(model)
    if config is not None:
        p_in, p_out = config.pricing()
    else:
        # Unknown model — fall back to a mid-range estimate.
        p_in, p_out = (3.00, 15.00)
    input_tokens = max(0, input_tokens)
    output_tokens = max(0, output_tokens)
    return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 6)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AttachedFile(BaseModel):
    name: str
    text: str  # pre-extracted text content


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    images: list[str] = []      # base64 data URLs
    files: list[AttachedFile] = []  # pre-extracted file contents
    model: str = DEFAULT_MODEL
    multi_agent: bool = False
    private: bool = False
    history: list[HistoryMessage] = []  # for private mode multi-turn
    continue_message_id: int | None = None  # continue a stopped assistant reply


class SessionInfo(BaseModel):
    session_id: str
    title: str
    message_count: int
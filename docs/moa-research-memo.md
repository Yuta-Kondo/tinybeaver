# Multi-agent mode — research memo

**Date:** 2026-08-03  
**Scope:** How to improve tinybeaver’s MoA / multi-agent chat, guided by recent papers (2024–2026).  
**Not a requirement:** Exactly five roles. Role count should serve diversity + quality, not a magic number.

## Implemented (2026-08-03)

Shipped as **Self-MoA on GLM**:

- Parallel proposers: **Advocate / Skeptic / Operator** (all `glm-5.2`, distinct temperatures)
- Each draft ends with `Confidence: 0.XX`; synthesizer is also GLM and weights by confidence
- No revise round (v1); discussion UI shows three role cards streaming at once
- Code: `backend/models.py` (`MOA_*`), `backend/main.py` (`generate_moa`), frontend `MoADrafts`

The sections below are the research notes that led to that design. The “Pre-Self-MoA design” subsection describes the old sequential pipeline for historical context.

---

## Pre-Self-MoA design (baseline, superseded)

Today’s pipeline is roughly:

1. **Advocate** (Gemini Flash) → recommendation  
2. **Skeptic** (GLM) → stress-test (sees prior draft)  
3. **Minimalist** (Haiku) → smallest next action (sees debate)  
4. **Synthesizer** (Claude Sonnet) → final answer  

Properties: **heterogeneous models**, **sequential** debate, **3 fixed personas**, **no confidence signals**, **always runs full depth**.

---

## What the papers actually recommend

### 1. Prefer one strong model over mixing weaker ones (Self-MoA)

**Paper:** *Rethinking Mixture-of-Agents: Is Mixing Different LLMs Beneficial?* ([arXiv:2502.00674](https://arxiv.org/abs/2502.00674), 2025)

- Classic MoA mixes proposers from different LLMs, then aggregates.
- **Self-MoA** aggregates several outputs from the **same top model**.
- Empirically, Self-MoA often **beats mixed MoA** (~6.6% on AlpacaEval 2.0; ~3.8% avg across MMLU / CRUX / MATH).
- Why: aggregator quality is bounded by proposal quality; mixing in weaker models **lowers average proposal quality** faster than it adds useful diversity.
- Diversity should come from **stochastic decoding + distinct prompts/roles**, not from “one of each vendor.”

**Implication for us:** If we standardize on **GLM** (or whichever single model we trust most for this mode), that aligns better with Self-MoA than Flash + GLM + Haiku + Sonnet.

### 2. Propose in parallel, then aggregate (MoA / RMoA / Voting)

**Papers:**

- *Mixture-of-Agents* ([arXiv:2406.04692](https://arxiv.org/abs/2406.04692), ICLR 2025) — layered propose → refine → aggregate; “collaborativeness” (models improve when shown other outputs).
- *RMoA* ([ACL Findings 2025](https://aclanthology.org/2025.findings-acl.342)) — maximize **diversity** among proposals; residual / incremental fusion; **distinct personas**; **adaptive early stop** when layers converge.
- *Voting or Consensus?* ([ACL Findings 2025](https://aclanthology.org/2025.findings-acl.606)) — **All-Agents Drafting (AAD)**: everyone drafts first (parallel), then decide/improve.

**Implication for us:** Replace strict Advocate→Skeptic→Minimalist chaining with:

1. **Parallel proposers** (same model, different role prompts + temperatures)  
2. Optional **one short revise** round (each sees others)  
3. **Single synthesizer**  

Sequential “tit-for-tat” is fine for adversarial debate papers, but for a personal assistant the parallel-then-fuse pattern is cheaper, less biased by speaking order, and closer to MoA/Self-MoA.

### 3. More agents can help; more rounds often hurt

**Paper:** *Voting or Consensus?* (ACL Findings 2025)

- Increasing **number of agents** improved performance.
- Increasing **discussion rounds before decision** often **hurt** (problem drift).
- **Voting** better for reasoning-style tasks; **consensus** slightly better for knowledge / fact-checking.
- Their AAD / Collective Improvement methods beat naive long debates.

**Implication for us:** Prefer **3–N diverse proposers + 1 synth**, with **≤1 revise round**. Don’t chase depth of debate.

Exact N is empirical; 3 is fine if prompts are sharp. 4–5 only if each role adds a non-overlapping lens. No evidence that “5” is special.

### 4. Diversity + confidence beat vanilla debate

**Paper:** *Demystifying Multi-Agent Debate: The Role of Confidence and Diversity* ([ACL Findings 2026](https://aclanthology.org/2026.findings-acl.1694.pdf))

- Vanilla MAD often fails to beat simple majority vote despite higher cost.
- Under homogeneous agents + uniform belief updates, debate **preserves** expected correctness (doesn’t systematically fix errors).
- Two interventions that help:
  1. **Diversity-aware initialization** — start with a diverse set of candidate views so the correct hypothesis is more likely present.
  2. **Confidence-modulated updates** — agents state calibrated confidence; others weight updates by that confidence.

**Implication for us:**

- Role prompts must force **different priors / lenses**, not three paraphrases of “be helpful.”
- Each proposer should emit an explicit **confidence** (e.g. 0–1 or low/med/high).
- Synthesizer should **weight** agreement by confidence, not treat every draft equally.

### 5. Roles matter; dynamic model↔role assignment is optional

**Papers:**

- Classic MAD / Multi-Persona (Liang et al., EMNLP 2024; ICLR 2025 blog surveys): affirmative / negative / judge, or angel / devil / judge.
- *Dynamic Role Assignment for Multi-Agent Debate* ([arXiv:2601.17152](https://arxiv.org/abs/2601.17152), 2026): Meta-Debate to pick **which model** fills **which role** per question — big gains when mixing models of unequal skill.

**Implication for us:**

- Keep **fixed, sharp roles** for a personal agent (predictable UX, low latency).
- Skip Meta-Debate unless we go back to multi-model mixtures; under Self-MoA (one model) dynamic model assignment is mostly irrelevant.
- Role design > role count.

### 6. Diverse *reasoning strategies* can beat fixed personas alone

**Paper:** *Breaking Mental Set… Diverse Multi-Agent Debate (DMAD)* (ICLR 2025)

- Same backbone, different **reasoning methods** (not only different character labels) breaks “mental set.”
- Outperformed fixed-persona MAD on several reasoning / multimodal benches, with fewer rounds needed.

**Implication for us (optional upgrade):** Mix role lenses *and* method hints, e.g. one agent “list assumptions then decide,” another “steelman the opposite,” another “constraint-first plan.” Still one model.

---

## Synthesized design principles

Ordered by how strongly the evidence supports them:

1. **One strong proposer model** (Self-MoA) — e.g. all-GLM for debate drafts; don’t dilute with Flash/Haiku for “variety.”
2. **Parallel proposals first** — avoid order bias and long serial latency.
3. **Diversity via prompts + temperature**, not via weaker models.
4. **Explicit confidence** on each proposal; synth uses it.
5. **Few rounds** — propose → (optional revise) → synthesize; stop early if high agreement / confidence.
6. **Roles that don’t overlap** — each must change the answer distribution, not the tone.
7. **Strong synthesizer** — can be the same model (Self-MoA) or a slightly stronger judge; one aggregation call is enough.
8. **Skip expensive meta-routing** unless mixing multiple models again.

---

## Suggested target architecture for tinybeaver

```
User query (+ memory / tools context)
        │
        ▼
 ┌────────────── parallel Self-MoA proposers (same model, e.g. GLM) ──────────────┐
 │  Role A          Role B           Role C         (optional Role D…)            │
 │  temp ~0.7       temp ~1.0        temp ~0.6                                    │
 │  + confidence    + confidence     + confidence                                 │
 └───────────────────────────────────┬────────────────────────────────────────────┘
                                     │
                     optional 1 revise round (see others)
                                     │
                                     ▼
                         Synthesizer / Judge (same or stronger)
                         — merge, weight by confidence
                         — one clear recommendation + dissent
                                     │
                                     ▼
                              Stream final answer (UI)
```

### Role pack (example — tune to Yuta; count flexible)

| Role | Job | Must produce |
|------|-----|----------------|
| **Advocate** | Best option + why | Top recommendation |
| **Skeptic** | Attack assumptions; offer alternative if flawed | Counter-proposal or hard risk |
| **Operator** | Time / money / energy / real constraints | Feasible plan under constraints |
| **Minimalist** *(optional)* | Smallest action this week | One concrete next step |

3 roles is enough to ship. Add a fourth only if gaps show up in real use (e.g. long-horizon / people impact).

### Decision rule for the synthesizer

- Prefer recommendations with **high confidence + surviving Skeptic pressure**.
- If proposers disagree strongly, surface **dissent** and pick the option that best fits Operator constraints + Minimalist next step.
- Prefer **voting-style** merge for “what should I do?”; prefer **consensus / fact-check** tone when the question is factual.

---

## Explicit non-goals (from the literature)

| Avoid | Why |
|-------|-----|
| Long multi-round debates by default | Problem drift; rounds can hurt (Voting/Consensus) |
| Mixing many mid models “for diversity” | Quality drop dominates (Self-MoA) |
| Meta-Debate for every chat | Costly; only needed for multi-model role assignment |
| Role count fetish (must be 5) | No paper establishes 5 as optimal; diversity of *content* matters |
| Identical “helpful assistant” personas | Fails diversity-aware init (Demystifying MAD) |

---

## Mapping: papers → product changes

| Change | Papers |
|--------|--------|
| GLM-only (or single-model) proposers | Self-MoA |
| Parallel draft SSE events, then synth | MoA, RMoA, AAD |
| Confidence field per draft | Demystifying MAD |
| Early stop / skip revise if agreement high | RMoA adaptive termination; Voting “fewer rounds” |
| Sharper non-overlapping role prompts | MAD / Multi-Persona; DMAD (methods) |
| Keep UI: show drafts + final | Existing UX; still valuable for trust |

---

## Open questions for implementation

1. **Synth model:** all-GLM vs GLM proposers + Sonnet judge (cost / quality tradeoff).  
2. **Tool use in MoA:** proposers with search/Gmail, or synth-only? (tools amplify cost × N).  
3. **When to enable MoA:** always-on toggle vs auto for high-stakes / ambiguous queries.  
4. **N and revise:** start with N=3, revise=0; A/B revise=1 on hard questions.  
5. **Evaluation:** personal “win rate” on saved hard decisions, not only public benches.

---

## Primary references

1. Li et al. — *Rethinking Mixture-of-Agents…* (Self-MoA), 2025. https://arxiv.org/abs/2502.00674  
2. Wang et al. — *Mixture-of-Agents Enhances LLM Capabilities*, ICLR 2025. https://arxiv.org/abs/2406.04692  
3. RMoA — ACL Findings 2025. https://aclanthology.org/2025.findings-acl.342  
4. *Demystifying Multi-Agent Debate…* — ACL Findings 2026. https://aclanthology.org/2026.findings-acl.1694.pdf  
5. *Voting or Consensus?* — ACL Findings 2025. https://aclanthology.org/2025.findings-acl.606.pdf  
6. *Dynamic Role Assignment for Multi-Agent Debate*, 2026. https://arxiv.org/abs/2601.17152  
7. DMAD — ICLR 2025. https://proceedings.iclr.cc/paper_files/paper/2025/file/3de667dab3b3d812583abc0a786139a0-Paper-Conference.pdf  
8. Liang et al. — MAD (divergent thinking), EMNLP 2024.  

---

## Bottom line

Ship a **Self-MoA-style** mode: **one strong model**, **parallel diverse role proposers**, **confidence-weighted synthesis**, **shallow depth**. Role count is a product knob (start at 3), not a research mandate.

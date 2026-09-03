# Provider data & pricing notes (tinybeaver models)

**In app:** Help panel (sidebar **?** or ⌘K → “Models & data privacy” / “Keyboard shortcuts”).  
Full research notes: this file. Summaries in `frontend/src/lib/helpContent.ts`.

**Date:** 2026-08-03  
**Scope:** Every chat model currently in [`backend/models.py`](../backend/models.py), plus how this app calls them.  
**Not legal advice** — policies change; re-check links before high-stakes decisions.

---

## Quick comparison

| Model (in app) | Provider / HQ | Where prompts go (typical) | Train on API data? | App list price ($/1M in→out) |
|----------------|---------------|----------------------------|--------------------|------------------------------|
| Haiku 4.5, Sonnet 4.6/5, Opus 4.8 | Anthropic (US) | US / “global” inference; workspace storage often US | **No** by default (commercial API) | Haiku 1→5; Sonnet 4.6 3→15; Sonnet 5 intro 2→10 (→3/15 after 2026-08-31); Opus 5→25 |
| Gemini 3.5 Flash | Google | Google infra (global unless Vertex-region pinned) | **No** if **paid** Gemini API / billing-enabled project; **Yes** on free/unpaid | App: 1.50→9.00 (verify vs live Gemini pricing page) |
| GLM-5.2 | Z.ai / Zhipu group (SG entity; PRC parent) | Z.ai says **Singapore** for API; group still PRC-linked | API DPA: **no store / no train** on content (stated) | **1.40→4.40** (Z.ai official; fixed Aug 2026) |
| *(not in app)* DeepSeek V4 | DeepSeek (Hangzhou, PRC) | **PRC** per privacy policy | Weaker / unclear vs US vendors; treat as high sensitivity | Flash 0.14→0.28; Pro 0.435→0.87 |

Also in the request path (not chat models): **Tavily** (web search), **your VPS SQLite** (memory, chats), **Gmail API** when connected.

---

## Anthropic (default daily path)

**Models:** `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-opus-4-8`  
**How we call:** Anthropic Messages API (`ANTHROPIC_API_KEY`); native tools (search, Gmail).

### Data

- Commercial API: **inputs/outputs not used for training** unless you opt in (e.g. feedback / partner programs).  
  Sources: [Is my data used for training?](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training), [API retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention).
- Retention: not “zero” by default; abuse/flagging and some model rules can keep data longer; **ZDR** available via sales.
- Residency: `inference_geo` can pin inference to `us` vs `global` on newer models; workspace at-rest geo is limited (US-centric as of docs reviewed).  
  Source: [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency).
- **Not “sent to China.”** US company, Western cloud stack.

### Pricing (app estimates)

| Model | $/1M in | $/1M out | Notes |
|-------|---------|----------|-------|
| Haiku 4.5 | 1.00 | 5.00 | |
| Sonnet 4.6 | 3.00 | 15.00 | |
| Sonnet 5 | 2.00 / 10.00 intro → 3.00 / 15.00 after **2026-08-31** | Time-based in code |
| Opus 4.8 | 5.00 | 25.00 | |

### Fit for tinybeaver

Best default for **personal memory + email + sensitive personal context**. Strongest contractual “no train on API” story among current options.

---

## Google Gemini

**Model:** `gemini-3.5-flash`  
**How we call:** `google-genai` with `GOOGLE_API_KEY` ([`backend/providers.py`](../backend/providers.py)) — i.e. **Gemini Developer API / AI Studio key**, not Vertex regional endpoints.

### Data

- **Paid / billing-enabled project:** Google says it **does not** use prompts/responses to improve products; processed under paid-service / DPA-style terms.  
  Sources: [Gemini API terms — Paid Services](https://ai.google.dev/gemini-api/terms), [Billing](https://ai.google.dev/gemini-api/docs/billing).
- **Free / unpaid quota:** may be used to improve Google products; human review possible — **do not treat as private**.
- Residency: Developer API is **not** the same as Vertex “pin to `europe-west1`.” Expect **global Google infrastructure** unless you move to Vertex with regional endpoints.
- **Not PRC-hosted**, but data can leave your country under Google’s global processing.

### Action item for you

Confirm the Cloud project behind `GOOGLE_API_KEY` shows **Paid** on the Gemini API key page. If it’s still free-tier, Gemini chats (and file extraction that uses Flash) are under the weaker data policy.

### Pricing

App estimate: **$1.50 in / $9.00 out** per 1M. Re-verify against [ai.google.dev pricing](https://ai.google.dev/gemini-api/docs/pricing) for the exact `gemini-3.5-flash` SKU (Google changes Flash lineups often).

### Fit for tinybeaver

Fine for speed/cost **if billed**. Weaker residency control than Anthropic-with-`us` or Vertex. Used for MoA historically and for attachment extraction.

---

## Z.ai / GLM (Self-MoA + selectable chat)

**Model:** `glm-5.2` (`zai/glm-5.2` via LiteLLM)  
**How we call:** `ZAI_API_KEY` → Z.ai OpenAI-compatible API.

### Data

- International operator: **Jingsheng Hengxing Technology Pte. Ltd. (Singapore)**; privacy/DPA text says services are **generally provided from Singapore**, customer data **generally processed in Singapore**.  
  Source: [Z.ai Privacy Policy / API DPA](https://docs.z.ai/legal-agreement/privacy-policy).
- API DPA claims: **do not store** customer/end-user content (inputs/outputs); **real-time processing**; process on customer’s behalf (i.e. not for their own training of that content — as stated).
- Corporate reality: Z.ai is the **international brand of Zhipu AI (Beijing)**. Group is still PRC-linked; Chinese law (e.g. intelligence / data security frameworks) is a **jurisdiction risk** even if the *stated* processing geo is Singapore. Same models exist on mainland endpoints with different terms — **use the Z.ai international API**, not bigmodel.cn, for the SG story.
- **Unlike DeepSeek’s English privacy policy, Z.ai does *not* say “we store this in the PRC.”** Treat as: **Singapore processing claimed + PRC-group residual risk**, not “identical to DeepSeek.”

### Pricing (official Z.ai, Aug 2026)

| | $/1M |
|--|------|
| Input | **1.40** |
| Cached input | 0.26 |
| Output | **4.40** |

App previously had **0.50 / 2.00** (wrong estimate); corrected to **1.40 / 4.40**.

### Fit for tinybeaver

Already used heavily for **Self-MoA** (3 proposers + synth) and optional chat. Cheaper than Sonnet; still far above DeepSeek Flash. Acceptable if you’re OK with Singapore + Zhipu-group risk for those workloads — **not the same “explicitly PRC storage” as DeepSeek**.

---

## DeepSeek (not integrated — research only)

**Latest IDs:** `deepseek-v4-flash`, `deepseek-v4-pro`  
**Official pricing:** [api-docs.deepseek.com pricing](https://api-docs.deepseek.com/quick_start/pricing)

| Model | Cache hit in | Cache miss in | Out |
|-------|--------------|---------------|-----|
| V4-Flash | 0.0028 | 0.14 | 0.28 |
| V4-Pro | 0.003625 | 0.435 | 0.87 |

Peak **2×** windows announced (Beijing time); effective date TBA.

### Data

- Privacy policy: **collect, process, and store personal data in the People’s Republic of China.**  
  Source: [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html).
- Direct API (`api.deepseek.com`): **yes — prompts go to China.** No US/EU residency toggle on the first-party API.
- Training / retention for API less clear and less “enterprise-default-no” than Anthropic/Google paid.

### Fit for tinybeaver

Great as an **optional cheap brain** for non-sensitive tasks. **Poor default** for a personal agent that injects life memory / mail. Prefer self-host or a Western host if you need DeepSeek quality without PRC storage.

---

## Side services in this app

| Service | Role | Data note |
|---------|------|-----------|
| **Tavily** | Web search prefetch / Claude `web_search` | Query + results leave your VPS to Tavily (US-based SaaS). Don’t put secrets in search queries. |
| **Gmail API** | Email tools | Google account data under Google’s Gmail/OAuth terms; only when you connect. |
| **Your VPS SQLite** | Chats, memory graph, docs | Data at rest on **your** Hetzner box — separate from LLM providers. Soft delete / private mode still matter for what you *send* to LLMs. |

---

## Practical guidance for this repo

1. **Default:** keep **Claude Sonnet 5** (or other Anthropic) for daily personal use.  
2. **Gemini:** confirm **paid** billing on the API project; otherwise treat as training-eligible.  
3. **GLM:** already in China-adjacent risk class via Zhipu group, but Z.ai’s **stated** story is Singapore + no API content storage — different from DeepSeek’s explicit PRC storage clause. Fine for MoA / optional chat if that tradeoff is OK.  
4. **DeepSeek:** add as **optional**, not default; never send Private-mode-off personal dumps there casually.  
5. **Cost tags** in the UI are estimates from [`MODELS`](../backend/models.py); they don’t replace provider invoices (and ignore cache hits, peak multipliers, tool fees).

---

## Primary links

- Anthropic training: https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training  
- Anthropic retention: https://platform.claude.com/docs/en/manage-claude/api-and-data-retention  
- Anthropic residency: https://platform.claude.com/docs/en/manage-claude/data-residency  
- Gemini terms: https://ai.google.dev/gemini-api/terms  
- Gemini billing / paid data: https://ai.google.dev/gemini-api/docs/billing  
- Z.ai privacy / API DPA: https://docs.z.ai/legal-agreement/privacy-policy  
- Z.ai pricing: https://docs.z.ai/guides/overview/pricing  
- DeepSeek pricing: https://api-docs.deepseek.com/quick_start/pricing  
- DeepSeek privacy: https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html  

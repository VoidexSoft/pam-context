# PAM Context: Task Complexity Classification

**Date:** 2026-04-01
**Status:** Approved
**Parent:** Universal Memory Layer Design (Phase 7 — LLM Gateway)
**Inspiration:** RouteLLM, AWS Bedrock Intelligent Prompt Routing, Portkey, Martian, Uber GenAI Gateway

## Vision

Route each LLM call to the cheapest model that can handle it well. A keyword extraction call doesn't need Opus. A multi-source variance analysis doesn't belong on Haiku. Task Complexity Classification sits inside the LLM Gateway and makes this decision automatically — using rules today, ML tomorrow.

## Approach: Hybrid (Rules now, ML later)

**Phase 1:** Rule-based `ComplexityClassifier` with configurable weights and thresholds. Every routing decision is logged with outcome signals.

**Phase 2:** When enough routing logs accumulate (~10,000 calls with quality signals), train a lightweight classifier. A/B test against rules. Classifier replaces rules when it wins consistently. Rules remain as fallback.

## Architecture

Task Complexity Classification is a sub-system of the LLM Gateway (Phase 7). It sits between the agent's LLM call request and the actual API call.

```
Agent Module (Doc, Graph, Data, etc.)
        │
        │  "I need an LLM completion"
        ▼
┌─────────────────────────────────────┐
│           LLM Gateway               │
│                                     │
│  ┌───────────────────────────────┐  │
│  │  Complexity Classifier        │  │
│  │  (signals → score → tier)     │  │
│  └──────────────┬────────────────┘  │
│                 ▼                    │
│  ┌───────────────────────────────┐  │
│  │  Model Selector               │  │
│  │  tier + config → model ID     │  │
│  └──────────────┬────────────────┘  │
│                 ▼                    │
│  ┌───────────────────────────────┐  │
│  │  LLM Client (Anthropic/etc)   │  │
│  └──────────────┬────────────────┘  │
│                 ▼                    │
│  ┌───────────────────────────────┐  │
│  │  Routing Logger               │  │
│  │  (decision + outcome → log)   │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

**Key distinction from the Supervisor Agent:**
- **Supervisor** decides *which agent* handles the query (Doc Agent vs Data Agent)
- **Complexity Classifier** decides *which model tier* each LLM call within that agent uses

A single user request can have multiple LLM calls at different tiers. The Supervisor's routing call might use Haiku, while the Data Agent's SQL generation uses Sonnet.

## Model Tiers

| Tier | Default Model | Use Cases | Cost Relative |
|------|--------------|-----------|---------------|
| **SIMPLE** | Haiku | Classification, extraction, keyword expansion, memory merging, intent routing | 1x (baseline) |
| **MODERATE** | Sonnet | Search + synthesis, SQL generation, single-agent answers, fact extraction | ~10x |
| **COMPLEX** | Opus | Multi-hop reasoning, cross-source synthesis, variance analysis, complex report generation | ~30x |

Tier-to-model mapping is configurable — when newer models launch, update config, not code:

```
LLM_TIER_SIMPLE=claude-haiku-4-5-20251001
LLM_TIER_MODERATE=claude-sonnet-4-6
LLM_TIER_COMPLEX=claude-opus-4-6
```

## Complexity Signals

The classifier extracts these signals from each LLM call request:

| Signal | Weight | How It's Measured | Low (simple) | High (complex) |
|--------|--------|-------------------|--------------|-----------------|
| **Prompt token count** | 0.15 | Token count of system + user prompt | < 500 tokens | > 4000 tokens |
| **Task type** | 0.30 | Labeled by the calling agent/function | `classify`, `extract`, `route` | `synthesize`, `analyze`, `compare` |
| **Tool count** | 0.15 | Number of tools provided in the call | 0-1 tools | 5+ tools |
| **Context sources** | 0.20 | How many knowledge sources feed the call | Single doc/memory | Docs + graph + memories + external DB |
| **Delegation depth** | 0.10 | Is this a sub-call from another agent? | Top-level or leaf call | Agent calling agent |
| **Conversation history** | 0.10 | Turns of conversation context included | 0-2 turns | 10+ turns |

### Scoring Formula

```
score = Σ(weight_i × normalize(signal_i))

score < 0.3  → SIMPLE
score < 0.7  → MODERATE
score >= 0.7 → COMPLEX
```

Each signal is normalized to [0, 1] via configurable breakpoints. Example for token count:
- 0.0 at ≤ 200 tokens
- 0.5 at 2000 tokens
- 1.0 at ≥ 6000 tokens

Weights, breakpoints, and thresholds are all configurable via Pydantic Settings.

## Escalation Mechanism

Agents can upgrade the model tier mid-task when they detect the work is harder than initially classified.

### Escalation Triggers

| Trigger | Detected By | Example |
|---------|------------|---------|
| **Tool call failure** | Agent gets malformed tool output or LLM fails to produce valid tool call | Haiku can't generate valid SQL for a complex join |
| **Retry threshold** | Same tool called 2+ times without progress | Model keeps producing wrong search queries |
| **Token budget exceeded** | Response hits max_tokens without completing | Answer is truncated mid-sentence |
| **Confidence signal** | Agent detects hedging patterns ("I'm not sure", "It's possible that") in a response to a factual query via regex check | Haiku hedges on a factual lookup that should have a definitive answer |
| **Multi-hop detected** | Agent discovers mid-task it needs to chain 3+ tool calls | Simple lookup turns into cross-source synthesis |

### Escalation Flow

```
Agent starts task (classified as SIMPLE → Haiku)
        │
        ▼
    LLM call #1 (Haiku)
        │
    Tool call fails / retry needed
        │
        ▼
    Agent calls gateway.escalate(reason="tool_call_failure")
        │
        ▼
    Gateway upgrades session tier: SIMPLE → MODERATE
        │
        ▼
    LLM call #2 (Sonnet) — continues with same context
        │
    Success
```

### Escalation Rules

- **One direction only** — tiers escalate up, never down within a session. Once upgraded to Sonnet, remaining calls in that agent session stay at Sonnet or higher.
- **Max one escalation per session** — SIMPLE → MODERATE or MODERATE → COMPLEX, not SIMPLE → COMPLEX in one jump. Prevents runaway cost if something is fundamentally broken.
- **Escalation is logged** — the routing logger captures `(original_tier, escalated_tier, reason, call_number)`. This is the most valuable training signal for the future ML classifier.
- **Agent-scoped, not request-scoped** — if the Data Agent escalates, the Doc Agent working on the same request keeps its own tier.

### Agent Tier Hints

Agents can provide a hint when making an LLM call, suggesting a minimum tier:

```python
response = await gateway.complete(
    prompt=prompt,
    tools=tools,
    min_tier=ModelTier.MODERATE,  # hint: don't use Haiku for this
)
```

The classifier still runs, but the final tier is `max(classified_tier, min_tier)`. This lets agents encode domain knowledge (e.g., "SQL generation should never use Haiku") without bypassing the classification system.

## Routing Logger

Every LLM call through the Gateway is logged with enough context to train a classifier later.

### Routing Log Record

```
RoutingLog {
  id:                UUID
  timestamp:         datetime
  request_id:        UUID        — ties all calls in one user request together
  agent_name:        str         — which agent made the call
  call_purpose:      str         — labeled by caller (classify, search, synthesize, generate_sql)

  # Classifier inputs
  signals:           JSONB       — raw signal values
  complexity_score:  float       — computed score (0.0 - 1.0)
  classified_tier:   enum        — SIMPLE / MODERATE / COMPLEX

  # Overrides
  agent_min_tier:    enum | null — agent's hint, if provided
  escalated_from:    enum | null — previous tier if escalated
  escalation_reason: str | null  — why escalation happened
  final_tier:        enum        — actual tier used

  # Outcome
  model_used:        str         — actual model ID
  input_tokens:      int
  output_tokens:     int
  latency_ms:        int
  cost_usd:          float       — computed from token counts + model pricing

  # Quality signals (filled async)
  success:           bool        — did the call produce a usable result?
  retried:           bool        — was this call retried?
  user_feedback:     str | null  — thumbs up/down if available
}
```

**Storage:** PostgreSQL table. Same DB as the rest of PAM.

**Retention:** Configurable, default 90 days. Aggregated stats kept indefinitely.

### Cost Analytics API

```
GET /api/admin/llm/usage
```

Returns:
- Cost breakdown by agent, by tier, by time period
- Escalation frequency and reasons
- Percentage of calls per tier (target: ~70% SIMPLE, ~25% MODERATE, ~5% COMPLEX)
- Cost savings vs. "everything on Sonnet" baseline

## Future ML Classifier

When enough routing logs accumulate (target: ~10,000 logged calls with quality signals), train a classifier to replace the rule-based scoring.

### Training Data

Each routing log becomes a training sample:
- **Features:** `signals` (token count, task type, tool count, etc.)
- **Label:** the tier that actually produced a good result:
  - If `success=true` and no escalation → `classified_tier` was correct
  - If escalated → `escalated_to` tier was the right answer
  - If `user_feedback=negative` → tier was possibly too low

### Model

Lightweight — embedding-based or gradient-boosted trees. Runs in-process, no external service. Sub-millisecond inference.

### Rollout

1. Classifier runs in **shadow mode** — scores every request but doesn't route. Logs `ml_predicted_tier` alongside `rule_predicted_tier`.
2. Compare ML vs. rules over a period. If ML produces fewer escalations and same/better quality → switch.
3. Rules remain as **fallback** when ML confidence is below a configurable threshold.

### Training Pipeline

No new infrastructure. Training happens offline via a management command:

```
python -m pam.llm.train_router
```

The trained model is a small artifact (~1MB) stored alongside the app.

## Integration with Existing PAM Components

### LLM Gateway Interface

```python
class LLMGateway:
    async def complete(self, prompt, tools=None, min_tier=None,
                       call_purpose=None, agent_name=None) -> Response:
        # 1. Classify
        signals = self.classifier.extract_signals(prompt, tools, call_purpose)
        tier = self.classifier.classify(signals)
        tier = max(tier, min_tier) if min_tier else tier

        # 2. Select model
        model = self.model_selector.get_model(tier)

        # 3. Call LLM
        response = await self.client.messages.create(model=model, ...)

        # 4. Log
        await self.routing_logger.log(signals, tier, model, response, ...)

        return response

    async def escalate(self, session_id, reason) -> ModelTier:
        # Bump session tier by one level, return new tier
```

### Migration of Existing Hardcoded Models

| Current Location | Current Model | After Integration |
|---|---|---|
| `keyword_extractor.py` — keyword extraction | Haiku (hardcoded) | Gateway with `call_purpose="extract_keywords"` → SIMPLE → Haiku |
| `query_classifier.py` — mode classification | Haiku (hardcoded) | Gateway with `call_purpose="classify_query"` → SIMPLE → Haiku |
| `memory/service.py` — content merging | Haiku (config) | Gateway with `call_purpose="merge_memory"` → SIMPLE → Haiku |
| `agent.py` — main agent loop | Sonnet (config) | Gateway with `call_purpose="synthesize"` → MODERATE → Sonnet |

Same behavior today, unified under one routing system. Individual components stop choosing their own models.

### Configuration

All settings nest under existing `PamSettings` (Pydantic Settings):

```python
# Tier-to-model mapping
llm_tier_simple: str = "claude-haiku-4-5-20251001"
llm_tier_moderate: str = "claude-sonnet-4-6"
llm_tier_complex: str = "claude-opus-4-6"

# Classifier weights (tunable)
complexity_weights: dict = {
    "token_count": 0.15, "task_type": 0.30, "tool_count": 0.15,
    "context_sources": 0.20, "delegation_depth": 0.10, "conversation_history": 0.10
}

# Thresholds
complexity_threshold_simple: float = 0.3
complexity_threshold_complex: float = 0.7

# Escalation
escalation_max_retries: int = 2
escalation_enabled: bool = True

# ML classifier (future)
ml_classifier_enabled: bool = False
ml_classifier_path: str = ""
ml_classifier_min_confidence: float = 0.8

# Routing log retention
routing_log_retention_days: int = 90
```

### Cost Tracker Replacement

The existing `CostTracker` in `agent.py` gets replaced by the Routing Logger — which does the same thing plus routing context.

## Design Principles

- **Transparent routing** — every decision is explainable via signal weights and scores
- **Configurable, not hardcoded** — weights, thresholds, tier-to-model mapping all in settings
- **Escalation over failure** — misclassification is recoverable, not catastrophic
- **Log everything** — routing decisions are the training data for the future ML classifier
- **No new infrastructure** — PostgreSQL for logs, in-process for classification, offline for training
- **Backward compatible** — existing components get the same models they use today, just routed through the Gateway

## References

- [RouteLLM — ICLR 2025](https://arxiv.org/abs/2406.18665) — trained router for strong/weak model routing
- [AWS Bedrock Intelligent Prompt Routing](https://aws.amazon.com/bedrock/intelligent-prompt-routing/) — 87% of prompts to Haiku, 63.6% cost savings
- [Portkey Task-Based Routing](https://portkey.ai/blog/task-based-llm-routing/) — feature-based scoring approach
- [Martian Model Router](https://withmartian.com/) — mechanistic interpretability for model selection
- [Uber GenAI Gateway](https://www.uber.com/blog/genai-gateway/) — enterprise LLM gateway pattern
- [OpenRouter Auto Router](https://openrouter.ai/docs/guides/routing/routers/auto-router) — request-level complexity analysis

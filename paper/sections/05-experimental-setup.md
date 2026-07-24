# 5 Experimental Setup

We evaluate seven contemporary models spanning three providers and roughly two
orders of magnitude in price: Anthropic `claude-opus-4-8`, `claude-sonnet-4-6`,
and `claude-haiku-4-5`; OpenAI `gpt-5` and `gpt-5-mini`; and, through OpenRouter,
Google `gemini-2.5-pro` and Meta `llama-4-maverick`. The model set was fixed
before results were examined.

Each model is queried through a provider-agnostic adapter with a uniform
generation configuration: temperature 0 where the provider permits it, and the
provider's fixed default for reasoning models that reject a temperature override.
Track A issues one generation per task; Track B runs the agent loop until the
model signals completion or exhausts its per-task token, tool-call, or wall-clock
budget. Spend is metered through a reservation-and-settlement ledger with a global
cap, so no run can exceed a preset budget.

Every reported cell is a single run over the full task set for that track (60
Track A tasks, 8 Track B tasks). Provider calls are wrapped in a transport layer
that retries transient failures — connection resets, read timeouts, HTTP 429 and
5xx responses, incomplete reads, malformed JSON, and empty completions — under a
bounded, deterministic backoff, while leaving deterministic HTTP 4xx errors
terminal so that a genuine request-construction bug surfaces rather than being
silently retried. This distinction matters: an early evaluation pass produced
spurious zero scores when concurrent load triggered rate limits and truncated
responses that ended agent episodes prematurely. We treat any run containing such
a truncation as invalid; every result in this paper comes from a complete,
untruncated run in which no task fell back to a baseline submission because of an
infrastructure failure, verified by inspecting each task's transcript for provider
errors. Total provider spend to produce the full two-track, seven-model evaluation
was on the order of tens of dollars.

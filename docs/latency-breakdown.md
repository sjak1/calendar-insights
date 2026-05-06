# Why does a query take ~9 seconds?

A short walkthrough of where time goes for a typical BriefingIQ AI query, with
real measurements from our standalone Bedrock benchmark and from production
traces. Aimed at sharing with non-engineering stakeholders.

---

## TL;DR

Every query goes through **2 LLM round-trips + 1 OpenSearch call**. There is a
hard floor of roughly **6-8 seconds** for any data-fetching query, set by the
LLM model speeds — not by our code. We've already cut several seconds off, but
sub-second isn't physically possible without skipping the LLM entirely.

---

## What happens for a typical query

Example: **"list 5 upcoming events this month"**

```
┌──────────────────────────────────────────────────────────────┐
│  USER hits Send                                              │
│         │                                                    │
│         ▼                                                    │
│  STEP 1 — Planning LLM call (Sonnet 4.6)         ~4-5 sec    │
│  • Reads system prompt + user query              cache helps │
│  • Picks tool, writes OpenSearch query            ~700ms      │
│         │                                                    │
│         ▼                                                    │
│  STEP 2 — Tool execution (Python)                ~0.4-2 sec  │
│  • Server replaces TODAY_START → 1777964400000   pure code   │
│  • OpenSearch query                                          │
│         │                                                    │
│         ▼                                                    │
│  STEP 3 — Synthesis LLM call (Haiku 4.5)         ~2-3 sec    │
│  • Reads tool results, writes the markdown reply ~half       │
│  • Returns to user                                Sonnet     │
│                                                              │
│  ───────────────────────────────────────                     │
│  Total                                            ~7-9 sec    │
└──────────────────────────────────────────────────────────────┘
```

---

## Where each second comes from

We benchmarked AWS Bedrock directly (no app code, just `boto3`) so we know
what the LLM service itself takes. Numbers are medians over 3 runs.

| Test | Sonnet 4.6 | Haiku 4.5 |
|------|------------|-----------|
| Just say "hi" — minimum round-trip | **2.2s** | **1.0s** |
| 290-token answer with tiny prompt | 23ms / token | **12ms / token** |
| 10k-token prompt processed (cold) | 3.0s | 1.3s |
| 10k prompt processed (cache warm) | 2.0s | 1.2s |
| Realistic — 10k cached prompt + ~80 token answer | **2.6s** | **1.6s** |

**What this tells us:**

- **There is a 1-2 second floor** on every call to Bedrock. That's network
  round-trip plus model warm-up. No prompt or code change can beat it.
- **Haiku is roughly 2× faster than Sonnet, per token, in every test.** That's
  an inherent property of the smaller model, not anything we control.
- **Cache reduces input cost** but only saves ~500-800ms. Output generation
  dominates whenever the model is asked to write more than a sentence.
- **Per-token output speed is the real bottleneck.** A 200-token reply takes
  ~5s on Sonnet vs ~2.5s on Haiku, regardless of how big the prompt is.

---

## What we've optimized so far

| Change | Impact | How |
|--------|--------|-----|
| Bedrock prompt caching | ~700ms saved per call | `cachePoint` markers around the static system prompt. |
| Sonnet/Haiku split routing | ~1.5s saved per query | Sonnet plans (smarter), Haiku writes the reply (faster). Verified with same-query A/B: Haiku 2.5s vs Sonnet 4.1s. |
| Parallel tool fan-out | 3-6s saved when LLM calls multiple tools | `ThreadPoolExecutor` runs tools concurrently. 4-tool fan-out: 7.9s sequential → 2.0s parallel. |
| Time-token substitution | ~2.7s saved on date-aware queries | Removed an extra LLM round-trip. LLM now writes `"TODAY_START"` and the server fills in epoch_ms before hitting OpenSearch. Cut iterations from 4 → 2. |
| Compact-output instruction | ~30% smaller responses | Single-line bullets instead of nested markdown tables. |

Net: typical query went from ~16s before any of this work to ~7-9s now.

---

## What we cannot speed up further (without trade-offs)

1. **The 1-2 second Bedrock floor.** Every call pays this. Only escape is
   bypassing the LLM for cases where we can answer with pure code (e.g. a
   "hello" greeting → ~30ms canned reply).
2. **Output generation is sequential.** If the answer is 200 tokens, Haiku
   needs ~2.4s to produce them. We can either accept this or force shorter
   replies by tightening the prompt.
3. **Streaming the response is blocked in production.** Mangum (the FastAPI
   adapter on Lambda) buffers responses end-to-end. Even if we generated
   tokens incrementally, the user wouldn't see them stream until the whole
   reply was done. Migrating to ECS or Lambda Function URL with response
   streaming would unlock perceived-latency wins (the user sees text as it's
   typed) but is a multi-day infra change.

---

## Levers we haven't pulled yet

- **Tighten the planning DSL** — bake the standard `_source` field list and
  `sort` into the system prompt so the planning LLM emits ~80 output tokens
  instead of 220. Estimated win: **~2s** off planning. Pure prompt edit.
- **Switch planning to Haiku** for simple lookups, fall back to Sonnet only
  when the query is ambiguous. Estimated win: **~3s** off planning. Risk:
  Haiku may build less precise queries.
- **Skip the synthesis LLM call** for tools that already return
  presentation-ready data (e.g. a single-event summary from BriefingIQ).
  Estimated win: **~2.5s**. Requires per-tool flagging.
- **Greeting/short-circuit bypass** — regex match for "hi", "hello", "thanks"
  in the API layer, return a canned string in ~30ms. Estimated win: 1.5-3s
  for those queries (~5% of traffic).

---

## The unfortunate truth

LLM-backed AI assistants are fundamentally measured in seconds, not
milliseconds. Even Anthropic's own [Claude.ai](https://claude.ai) and OpenAI's
ChatGPT take 3-10 seconds per response. The interaction model is built around
*streaming text* so the user sees progress, which makes the wait feel shorter
even when total time is similar.

Once Lambda streaming is unblocked, the user will start seeing the answer
appear at ~2 seconds (when synthesis begins) and finish at ~7-9 seconds —
which feels much faster than waiting silently for 9 seconds and then seeing
the full block.

---

## Reproducing these numbers

- Live waterfall per query: open `http://<host>/static/timings.html`, type a
  query, watch the colored bars grow as each step starts and finishes.
- Bedrock-only bench (no app code): `python bench_bedrock.py` from the
  project root. ~3 minutes. Outputs the table in this doc.

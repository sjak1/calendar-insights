# BriefingIQ AI Assistant (calender-insights)

A natural-language **AI agent** for the BriefingIQ event-management platform. Users
ask questions in plain English ("what rooms are free Friday afternoon?", "draft a
confirmation email for the keynote presenter") and the agent plans a response,
calls a suite of tools against BriefingIQ APIs, OpenSearch, and SQL backends —
iterating over as many tool rounds as the task needs — then synthesises an answer
or takes the action.

It's a full tool-calling agent loop, not a single prompt: the model decides which
tools to call, the server runs them (in parallel when it can), feeds the results
back, and the model keeps going until it has enough to respond.

Backed by AWS Bedrock (Claude Sonnet 4.6 by default), with optional OpenAI and
GLM-5.2 providers behind the same loop. Deployed as an AWS Lambda container;
runnable locally as a FastAPI service.

## Architecture

```
                  ┌────────────────────────┐
   HTTP / SSE ──▶ │   api.py  (FastAPI)    │
                  └──────────┬─────────────┘
                             │
                  ┌──────────▼─────────────┐
                  │  query_processor.py    │  agent loop: LLM ↔ tools (≤15 rounds)
                  │  • Bedrock/OpenAI/GLM  │  prompt caching · parallel tools
                  │  • session + memory    │  identity → access scope · cost accounting
                  └──────────┬─────────────┘
                             │
        ┌────────────────────┼────────────────────────┐
        ▼                    ▼                        ▼
  tools/handlers.py    opensearch_client.py    database.py (SQL)
  • list_rooms         • event/activity        • session store
  • find_vacant_slots    history search        • user memories
  • block_calendar     • search()/count() with
  • push_agenda          RBAC filter injected
  • drafts (email/…)     (server-side, mandatory)
  • presenter_suggest
  • briefingiq_writer
  • generate_agenda
  • reports (chart/PDF)
```

Key modules:

- [api.py](api.py) — FastAPI app with `/process_query` (JSON) and
  `/process_query_stream` (SSE waterfall of LLM + tool events).
- [query_processor.py](query_processor.py) — agent loop, Bedrock/OpenAI dispatch,
  prompt caching, parallel tool execution.
- [bedrock_llm.py](bedrock_llm.py) — Bedrock Converse wrapper, OpenAI-tools →
  Bedrock-tools translation.
- [tools/](tools/) — function-calling tool implementations (see
  [docs/tools.md](docs/tools.md) for the full catalog).
- [memory_manager.py](memory_manager.py) — per-user long-term memory (Postgres).
- [session_manager.py](session_manager.py) — short-term chat history.
- [opensearch_client.py](opensearch_client.py) — wraps the events/activities
  index for history and similarity search.
- [lambda_handler.py](lambda_handler.py) — Mangum adapter for AWS Lambda.

## What the agent can do

The core of the service is an agentic tool-calling loop
([query_processor.py](query_processor.py)), not a one-shot prompt. Highlights:

- **Multi-step reasoning + tool use** — up to 15 LLM↔tool iterations per query;
  the agent decides at each step which tools to call and when it has enough to
  answer.
- **Parallel tool execution** — when the model requests several tools at once, the
  server fans them out on a thread pool, turning total latency into
  `max(tool_time)` instead of the sum ([tools/handlers.py](tools/handlers.py)).
- **17 first-class tools** — room/resource discovery, vacant-slot finding, calendar
  blocking, OpenSearch search/count, agenda generation, presenter suggestion,
  chart/PDF/report generation, and drafting (confirmation emails, catering sheets).
  See [docs/tools.md](docs/tools.md).
- **Pluggable LLM backend** — one loop, three providers: AWS Bedrock (Claude Sonnet
  4.6, default), OpenAI, or GLM-5.2 via NVIDIA's OpenAI-compatible API (`USE_GLM=1`).
  An optional split-model mode can route synthesis to Claude Haiku.
- **Prompt caching** — the static ~9k-token system prefix (instructions + schema
  reference) is marked with Bedrock `cachePoint`s and reused across every
  iteration, so only the per-query delta is re-billed.
- **Live streaming waterfall** — `/process_query_stream` emits SSE lifecycle events
  (`llm_start`/`llm_end`, `tool_start`/`tool_end`, `query_end`) so a client can
  render, in real time, exactly where each millisecond went.
- **Per-query token + cost accounting** — responses carry input/output token counts
  and an estimated Bedrock dollar cost.
- **Server-side date resolution** — relative-date tokens (`TOMORROW_START`,
  `THIS_WEEK_END`, …) and ISO dates in the model's OpenSearch queries are
  substituted to epoch-millis on the server, saving a `get_time_context`
  round-trip.
- **Role-based access enforcement (RBAC)** — the caller's identity (from the
  `X-Cloud-*` headers) is resolved to a data scope from the briefing app's Oracle
  access model, compiled into a mandatory OpenSearch filter, and injected at the
  single `search()`/`count()` chokepoint — *server-side, so the LLM can't remove or
  bypass it*. Access-resolution failures fail closed (deny). See the
  [access model guide](docs/RBAC_ACCESS_MODEL_GUIDE.md).

## Quick start (local)

Requires Python 3.12.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # fill in Bedrock + OpenSearch credentials
uvicorn api:app --reload --port 8000
```

Then POST a query:

```bash
curl -X POST http://localhost:8000/process_query \
  -H "Content-Type: application/json" \
  -H "X-Cloud-EventId: <event-uuid>" \
  -H "X-Cloud-User: someone@example.com" \
  -d '{"query": "what rooms are free tomorrow afternoon?", "headers": {}}'
```

Open `http://localhost:8000/` for the bundled chat UI (served from
[static/](static/)). It also renders a live latency waterfall via the SSE
endpoint.

## Configuration

All config is via environment variables — see [.env.example](.env.example) for
the full list. Highlights:

| Variable | Purpose |
|---|---|
| `USE_BEDROCK` | `1` (default) uses AWS Bedrock; `0` falls back to OpenAI |
| `USE_GLM` / `LLM_PROVIDER=glm` | Route the loop through GLM-5.2 (NVIDIA OpenAI-compatible API); takes precedence over Bedrock |
| `GLM_MODEL_ID` | GLM model id (default `z-ai/glm-5.2`) |
| `BEDROCK_MODEL_ID` | Defaults to `us.anthropic.claude-sonnet-4-6` |
| `bedrock_api_key` | Bedrock API key (boto3 reads as `AWS_BEARER_TOKEN_BEDROCK`) |
| `AWS_REGION` | AWS region for Bedrock + Lambda (default `us-west-2`) |
| `OPENSEARCH_URL` / `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` | OpenSearch cluster used for events + activity history |
| `USE_HAIKU_SYNTHESIS` | Optional split-model routing (off by default) |

The query expects request headers identifying the calling user and event
context: `X-Cloud-EventId`, `X-Cloud-CategoryId`, `X-Cloud-User`,
`X-Cloud-CustomerId`, and the `X-Cloud-*-Timezone` set. These shape the agent's
defaults (e.g. which rooms to consider, which timezone to interpret "tomorrow"
in).

## Tools (function calling)

The assistant calls tools registered in [tools/definitions.py](tools/definitions.py)
and dispatched by [tools/handlers.py](tools/handlers.py). Categories:

- **Discovery** — `list_rooms`, `list_event_activities`,
  `get_resource_schedule`, `find_vacant_slots`.
- **Writes to BriefingIQ** — `block_calendar`, `push_agenda_to_app`,
  presenter assignment.
- **Drafts** — confirmation emails, catering sheets (see
  [tools/drafts.py](tools/drafts.py)).
- **Presenter intelligence** — historical suggestion via OpenSearch
  ([tools/presenter_suggest.py](tools/presenter_suggest.py)).
- **Reports & charts** — PDF/PPTX generation.

For the full per-tool contract and the underlying BriefingIQ REST calls, see:

- [docs/tools.md](docs/tools.md)
- [docs/briefingiq-api-reference.md](docs/briefingiq-api-reference.md)
- [docs/latency-breakdown.md](docs/latency-breakdown.md)

## Database

Postgres is used for session history and per-user long-term memories. Schema
migrations live in [migrations/](migrations/) — apply them in numeric order
against the configured database before running the app.

## Deployment (AWS Lambda)

The service ships as a container image to ECR and runs on Lambda behind API
Gateway.

```bash
./setup_ecr.sh          # one-time: create the ECR repo
./build_and_deploy.sh   # build, tag, push, update Lambda
```

The [Dockerfile](Dockerfile) uses the AWS Lambda Python 3.12 base image and
invokes `lambda_handler.handler` (Mangum adapter over the FastAPI app).

## Tests & benchmarks

- `pytest` runs the test suite (see `test_*.py` at repo root).
- [bench_bedrock.py](bench_bedrock.py) benchmarks Bedrock latency/throughput
  across models.
- [run_q.py](run_q.py) is a small CLI for sending an ad-hoc query through the
  pipeline without spinning up FastAPI.

## Repository map

```
api.py, query_processor.py, bedrock_llm.py   core service
tools/                                       function-calling tools
docs/                                        API reference, tool catalog, latency notes
migrations/                                  Postgres schema migrations
scripts/                                     one-off utilities
static/                                      bundled chat UI
config/, data/, documents/                   reference data
build_*.sh, setup_ecr.sh, Dockerfile         packaging + deploy
```

## Further reading

- [TODO.md](TODO.md) — outstanding work
- [PROJECT_CHANGES.md](PROJECT_CHANGES.md) — historical change log
- [client_req_todo.md](client_req_todo.md) — client requirement tracker

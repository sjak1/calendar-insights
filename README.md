# BriefingIQ AI Assistant (calender-insights)

Natural-language AI assistant for the BriefingIQ event-management platform. Users
ask questions in plain English ("what rooms are free Friday afternoon?", "draft a
confirmation email for the keynote presenter") and the assistant calls a suite of
tools against BriefingIQ APIs, OpenSearch, and SQL backends to answer or take
action.

Backed by AWS Bedrock (Claude Sonnet 4.6 by default, with optional OpenAI
fallback). Deployed as an AWS Lambda container; runnable locally as a FastAPI
service.

## Architecture

```
                  ┌────────────────────────┐
   HTTP / SSE ──▶ │   api.py  (FastAPI)    │
                  └──────────┬─────────────┘
                             │
                  ┌──────────▼─────────────┐
                  │  query_processor.py    │  agent loop: LLM ↔ tools
                  │  • Bedrock Converse    │
                  │  • session + memory    │
                  └──────────┬─────────────┘
                             │
        ┌────────────────────┼────────────────────────┐
        ▼                    ▼                        ▼
  tools/handlers.py    opensearch_client.py    database.py (SQL)
  • list_rooms         • event/activity        • session store
  • find_vacant_slots    history search        • user memories
  • push_agenda
  • drafts (email/catering)
  • presenter_suggest
  • briefingiq_writer
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

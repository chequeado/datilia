# data360-claim-contextualizer

A Django REST API that contextualizes journalistic claims against World Bank [Data360](https://data360.worldbank.org) data. Given a claim like *"Argentina's poverty rate reached 39% in 2022"*, it searches for relevant indicators via an AI agent, extracts verified data points, and returns a citeable narrative with structured annotations.

Built by [Chequeado](https://chequeado.com).

---

## How it works

The `/contextualize` endpoint runs an 8-step pipeline:

1. **Tool loop** — an LLM agent searches Data360 via MCP tools (multi-turn)
2. **Resolver** — a second LLM call extracts a structured `ResolvedQuery` (indicator, countries, time range)
3. **Early exit** — if the claim is not verifiable (opinion, out of scope, no data), return immediately
4. **Claim set** — data points are extracted from the agent's tool trace into typed `Claim` objects
5. **Chart spec** — a Vega-Lite visualization is requested from the Data360 MCP server
6. **Narrative writer** — a third LLM call produces a 2–4 sentence paragraph with `[[claim_id:value]]` citation tags
7. **PCN verifier** — tags are parsed and each cited value is matched back to the claim set; bare numbers are flagged
8. **Response assembly** — everything is combined and returned as structured JSON

---

## Stack

| Layer | Technology |
|---|---|
| API | Django 4.2 + Django REST Framework |
| AI / agents | OpenAI Agents SDK |
| Data tools | World Bank Data360 via MCP (Model Context Protocol) |
| Config | Pydantic Settings |
| Server | Gunicorn (app) + Uvicorn (MCP) |
| Containers | Docker + docker-compose |

---

## Quickstart

### Docker (recommended)

```bash
cp .env.example .env          # fill in OPENAI_API_KEY and DJANGO_SECRET_KEY
docker-compose up
```

- App: `http://localhost:8080`
- MCP server: `http://localhost:8000/mcp`
- Sandbox UI: `http://localhost:8080/`

### Local development

```bash
cp .env.example .env
uv sync

# Terminal 1 — MCP server
cd data360-mcp
uv run uvicorn data360.server:app --host 0.0.0.0 --port 8000

# Terminal 2 — Django app
uv run python manage.py runserver 8080

# Verify MCP connectivity
uv run python scripts/probe_mcp.py
```

---

## API

### `POST /contextualize`

**Request**
```json
{
  "claim": "Argentina's poverty rate reached 39.2% in 2022",
  "context": "optional background",
  "language": "es",
  "preferred_country": "ARG"
}
```

**Response** (abbreviated)
```json
{
  "status": "ok",
  "trace_id": "...",
  "is_verifiable": true,
  "indicator_code": "SI_POV_NAHC",
  "indicator_name": "Poverty headcount ratio",
  "narrative": "La tasa de pobreza en Argentina fue [[SI_POV_NAHC_ARG_2022:39.2]]% en 2022...",
  "narrative_segments": [...],
  "chart_spec": { },
  "claim_set": [...],
  "tool_trace": [...]
}
```

---

## Configuration

All settings are read from environment variables (see `.env.example`):

---

## Project layout

```
ai/           LLM client, MCP client, prompts, agentic tool loop
api/          Django views, serializers, URL routing
pipeline/     Orchestrator + claim extraction, chart building, tag verification
scripts/      Developer utilities (probe_mcp.py)
tests/        Test suite
config.py     Pydantic settings
manage.py     Django CLI
```

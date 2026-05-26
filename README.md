# Datilia

**Datilia** is a prototype tool developed by [Chequeado](https://chequeado.com) for the **Media Party × World Bank Data360 Global Challenge**.

Given a journalistic text, Datilia identifies verifiable statistical claims, searches the [World Bank Data360](https://data360.worldbank.org) database via an AI agent, and returns a narrative paragraph with data context and a Vega-Lite chart.

<img width="1408" height="812" alt="Captura de pantalla de 2026-05-26 17-25-27" src="https://github.com/user-attachments/assets/2d22528b-b450-4ecf-ae85-33753afaa393" />

---

## Live demo

**[datilia.chequeado.com](https://datilia.chequeado.com)** |
[Live Example](https://datilia.chequeado.com/run/63f479fe-7674-44e4-839e-315cb21dd2dc)

The deployed prototype is password-protected:

| | |
|---|---|
| User | `data360` |
| Password | `data360challenge` |

---

## Table of Contents

- [Live demo](#live-demo)
- [What we built](#what-we-built)
- [Stack](#stack)
- [Quickstart](#quickstart)
  - [Docker (recommended)](#docker-recommended)
  - [Local development](#local-development)
- [API](#api)
- [Configuration](#configuration)
- [Technical Documentation](#technical-documentation)
  - [Architecture Overview](#architecture-overview)
  - [Data360 API Integration Methodology](#data360-api-integration-methodology)
  - [Security & Data Protocols](#security--data-protocols)
- [User Guide](#user-guide)
  - [Frontend Sandbox (`/`)](#frontend-sandbox-)
  - [Run History (`/history`)](#run-history-history)
  - [API Documentation (`/docs`)](#api-documentation-docs)
- [Sustainability & Maintenance](#sustainability--maintenance)

---

## What we built

This prototype was developed end-to-end for this challenge. Beyond wiring up the Data360 MCP server, the work included:

- **Claim extractor** — an LLM-based pre-screen that reads a journalistic text and identifies which statements are quantitative, country-level, and plausibly verifiable against international statistical databases. Opinions, qualitative assertions, and non-statistical claims are filtered out before any data query runs.

- **Editorial agent prompt** — a custom system prompt that shapes how the agent uses the Data360 tools. It enforces Chequeado's editorial standard, including things like mandatory comparability checks before cross-country comparisons and a strict scope rule that limits the agent to the submitted claim. 

- **AI chart type selector** — a second LLM call that takes the retrieved dataset and the agent's finding and picks a visualization strategy. Nine strategies are available based on our criteria, and the selector chooses based on both data shape and the editorial story in the claim, then assigns every encoding channel (axes, color, facet, highlight). This provides better graphs tailored to the editorial intent.

- **Iterative correction system** — every result can be refined by natural-language instruction without starting over. Chart corrections re-run only visualization (no new data fetch); data corrections re-run the full agent with the instruction added as context.

---

## Stack

| Layer | Technology |
|---|---|
| API | Django 4.2 + Django REST Framework |
| AI / agents | OpenAI Agents SDK |
| Data tools | World Bank Data360 via MCP (Model Context Protocol) |
| Visualization | Vega-Lite DataWrapper |
| Config | Pydantic Settings |
| Server | Gunicorn (app) + Uvicorn (MCP) |
| Containers | Docker + docker-compose |

---

## Quickstart

### Docker (recommended)

```bash
cp .env.example .env          # fill in OPENAI_API_KEY and DJANGO_SECRET_KEY
docker compose up
```

- App: `http://localhost:8090`
- MCP server: `http://localhost:8000/mcp`
- API docs: `http://localhost:8090/docs`

### Local development

```bash
cp .env.example .env
uv sync

# Terminal 1 — MCP server
cd data360-mcp
uv run uvicorn data360.server:app --host 0.0.0.0 --port 8000

# Terminal 2 — Django app
uv run python manage.py runserver 8090
```

---

## API

Full interactive documentation is available at `/docs` (Scalar UI) once the app is running.

---

## Configuration

All settings are read from environment variables (see `.env.example`):

---

## Technical Documentation

### Architecture Overview

Datilia is composed of two independent services that communicate over HTTP:

```
┌─────────────────────────────────────────────────────┐
│                   Django App (:8090)                │
│                                                     │
│  POST /contextualize                                │
│       │                                             │
│       ▼                                             │
│  1. Claim extraction  ──► LLM (structured output)  │
│  2. Agent tool loop   ──► MCP client ──────────────┼──► Data360 MCP (:8000)
│  3. Data extraction   ──► parse tool trace          │         │
│  4. Chart selection   ──► LLM (structured output)  │    World Bank Data360 API
│  5. Chart building    ──► Vega-Lite spec builder    │
│                                                     │
│  SQLite / ORM persistence (runs, corrections)       │
└─────────────────────────────────────────────────────┘
```
---

### Data360 API Integration Methodology

Datilia fetches all World Bank data through the **[data360-mcp](https://github.com/worldbank/data360-mcp)** server — an open-source MCP (Model Context Protocol) server developed by the World Bank's AI for Data team. Rather than calling the Data360 REST API directly, Datilia's agent connects to this MCP server and uses its tools as callable functions.

**Why MCP?** The raw Data360 API requires knowing indicator IDs, country codes, and filter parameters upfront. The MCP server abstracts that complexity: it provides search, validation, and retrieval tools designed specifically for LLM agents, including server-side country coverage checks and chain-of-thought guidance resources.

---

### Security & Data Protocols

**Data provenance.** All data served by Datilia originates from the World Bank Data360 platform via the official MCP server. No data is fabricated or cached beyond the single run stored in SQLite. The indicator name, source, unit, and any stated limitations are captured from the MCP response and stored alongside each run.

**No user data retention beyond runs.** The only data persisted is the claim text, the agent trace, and the resulting chart spec — all scoped to a single `trace_id`. There is no user authentication layer in the prototype; access control is the operator's responsibility when deploying behind a reverse proxy.

**LLM output validation.** Both LLM calls (claim extraction and chart selection) use structured output with Pydantic schemas enforced via the OpenAI `parse` API, preventing free-form text from reaching downstream rendering logic.

**Dependency surface.** The MCP server runs in an isolated container with no write access to the host filesystem. The Django app runs as a non-root user inside its container. Gunicorn is fronted by Nginx in production deployments.

---

## User Guide

Once the app is running at `http://localhost:8090`, there are three main pages:

### Frontend Sandbox (`/`)

The main interface for exploring claims in a journalistic text.

1. **Paste a text** — any news article or paragraph in any language. The model defaults to Spanish output but adapts to the input language.
2. **Click "Contextualizar"** (or press `Ctrl+Enter`) — the app calls `/extract-claims` and highlights each detected verifiable statistical claim inline.
3. **Click a highlighted claim** — this triggers the full `/contextualize` pipeline for that specific claim. A spinner appears while the agent searches Data360.
4. **Review the result card** — each result shows:
   - The matched indicator and data source
   - A narrative paragraph contextualizing the claim with real data
   - An interactive Vega-Lite chart
5. **Corrections** — if the chart type or data is not ideal, use the correction field to send a natural-language instruction (e.g. *"show only Latin American countries"* or *"use a line chart instead"*). The app will re-run chart selection or the full pipeline accordingly.
6. **Export to Datawrapper** — if a Datawrapper API key is configured, the chart can be published directly from the result card.

**Color coding of highlighted claims:**
- Yellow — pending / not yet processed
- Green — successfully contextualized
- Gray — no matching indicator found (`is_verifiable: false`)
- Red — pipeline error

### Run History (`/history`)

Lists all previous contextualization runs with their claim text, indicator matched, and status. Click any row to open the full run detail.

### API Documentation (`/docs`)

Interactive OpenAPI reference (Scalar UI) for all endpoints. Useful for integrating Datilia into other tools or testing the API directly from the browser.

---

## Sustainability & Maintenance

Datilia is a working prototype built around open standards:

- **MCP** (Model Context Protocol) for tool use — any MCP-compatible data source can be swapped in
- **Vega-Lite** for visualization — specs are portable and embeddable
- **Datawrapper** integration for publication-ready chart export
- **SQLite** persistence with a clean Django ORM schema — trivially migrated to Postgres

**Sustainability model.** A production-ready version of this tool could be offered as a SaaS to newsrooms and other organizations that work with development data — providing a revenue stream that directly funds the AI token costs for NGO and non-commercial users. Self-hosting is always an option since the project is fully open source under MIT. On the data side, scaling to cover additional datasets beyond Data360 (e.g. UN databases, national statistics offices) would meaningfully expand the tool's utility and reach.

---

**Prototype constraints.** The static HTML frontend (`static/`) and SQLite database reflect the nature of this project as a hackathon prototype — chosen for simplicity and zero-dependency deployment. A production version would naturally replace these with a React (or similar) frontend and a more robust database such as PostgreSQL; both are straightforward swaps given that the Django ORM abstracts the database layer and the frontend communicates exclusively through the REST API.

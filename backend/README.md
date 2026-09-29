# SRE AI Incident Response — Backend Foundation

## 1. Project purpose

Layered FastAPI backend for the SRE AI Incident Response project. Right now it
establishes only the foundation:

- a clean `API -> Service -> Hindsight Cloud` separation, and
- Hindsight Cloud as the organizational memory layer (retain/recall incidents).

No AI agent, simulator, remediation, or frontend is included by design. The
future agent will follow
`Observe -> Investigate -> Recall -> Reason -> Act -> Verify -> Learn`, with
Hindsight serving the **Recall** step.

## 2. Architecture

```text
backend/
├── app/
│   ├── main.py                 # FastAPI app, router wiring
│   ├── config/settings.py      # env-based config (pydantic-settings)
│   ├── api/routes/
│   │   ├── health.py           # GET /health
│   │   └── memory.py           # POST /memory/test, POST /memory/recall
│   ├── services/
│   │   └── hindsight_service.py # ONLY place that imports hindsight_client
│   ├── models/incident.py      # Incident / RecallQuery Pydantic models
│   └── core/dependencies.py    # singleton HindsightService dependency
└── tests/test_hindsight.py     # mocked SDK tests, no credentials needed
```

Layer rule:

```text
API Layer (routes)
    ↓ (dependency injection)
Service Layer (HindsightService)
    ↓ (hindsight-client SDK)
Hindsight Cloud
```

Routes never import the SDK directly. The future shape this enables:

```text
API
 ↓
Agent Service
 ↓
 ┌───────────────┐
 │               │
Hindsight      Tools
Memory         Actions
 │               │
 └───────┬───────┘
         ↓
      Simulator
```

## 3. Installation

Requires Python 3.11+.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Environment variables

| Variable            | Required | Default                                |
| ------------------- | -------- | -------------------------------------- |
| `HINDSIGHT_API_KEY` | yes      | (none — never hardcoded)               |
| `HINDSIGHT_BASE_URL`| no       | `https://api.hindsight.vectorize.io`   |
| `HINDSIGHT_BANK_ID` | no       | `sre-organizational-memory`            |

```powershell
Copy-Item .env.example .env
# then edit .env and paste your Hindsight Cloud API key
```

`.env` is gitignored; only `.env.example` is committed.

## 5. How to run the FastAPI server

```powershell
cd backend
uvicorn app.main:app --reload
```

Docs: <http://127.0.0.1:8000/docs>

## 6. How to test `/health`

```powershell
curl http://127.0.0.1:8000/health
```

Expected:

```json
{ "status": "ok" }
```

## 7. How to test Hindsight retain/recall

Retain one realistic incident (payment-api pool exhaustion) and recall it:

```powershell
curl -X POST http://127.0.0.1:8000/memory/test
```

Recall-only (no retain):

```powershell
curl -X POST http://127.0.0.1:8000/memory/recall `
  -H "Content-Type: application/json" `
  -d '{"query": "payment API 5xx database connection pool exhaustion"}'
```

Run the offline test suite (mocked SDK, no key needed):

```powershell
pytest -v
```

## 8. Example expected response

`POST /memory/test` (truncated):

```json
{
  "bank_id": "sre-organizational-memory",
  "retain": {
    "incident_id": "INC-2024-001",
    "bank_id": "sre-organizational-memory",
    "success": true
  },
  "query": "Find previous production incidents involving payment API ...",
  "recall_count": 1,
  "memories": [
    {
      "text": "Incident INC-2024-001: payment-api ... Root cause: Database connection pool exhaustion ...",
      "score": 0.9,
      "metadata": { "incident_id": "INC-2024-001", "service": "payment-api" }
    }
  ]
}
```

Error cases return developer-facing messages without secrets:

- missing key → `503` with "HINDSIGHT_API_KEY is not set ..."
- Cloud/API/network failure → `502` with a redacted message
- empty recall query → `422`

## 9. Current limitations

- No persistence besides Hindsight Cloud (no database).
- Single hardcoded sample incident for the smoke test.
- No auth on endpoints (local/dev only).
- Recall result shape depends on the SDK version (`text/score/metadata`
  normalized best-effort in `HindsightService._serialize_result`).
- Sync `TestClient`-based tests; live Cloud test needs a real key.

## 10. Planned future layers

1. Incident simulator producing `Incident` payloads.
2. Agent service (`Observe -> Investigate -> Recall -> Reason -> Act -> Verify`).
3. Tool/action layer for remediation (pool resize, restart, rollback).
4. Verify + Learn loop writing outcomes back via `retain_incident`.
5. Auth, persistence, evals, frontend.

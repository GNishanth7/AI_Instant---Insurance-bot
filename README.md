# Health Insurance Plan Assistant

Health insurance assistant built on local policy JSON files (`4d_health_*.json`) with a FastAPI backend and Next.js frontend.

## Overview

The app lets users:

- Ask coverage questions for a selected plan
- Get citations from policy sections
- Run a guided claim workflow
- Run a guided appointment workflow
- Generate a professional claim PDF at the end of the claim flow

## Tech Stack

- Backend: FastAPI (`backend/server.py`)
- Frontend: Next.js 15 + React 19 (`frontend/`)
- Retrieval: sentence-transformers + FAISS (`core/retriever.py`)
- Optional answer generation: Gemini via `google-genai` with local fallback (`core/llm.py`)
- Claim PDF generation: `fpdf2` (`core/pdf_generator.py`)

## Project Structure

```text
backend/              API routes and service layer
core/                 ingestion, retriever, llm, pdf generator
workflows/            claim and appointment state machines
frontend/             Next.js UI + API proxy route
faiss_index/          generated vector indexes per plan
generated_claims/     generated claim PDFs
4d_health_*.json      policy source files
```

## How It Works

1. Plan files are discovered from `4d_health_*.json`.
2. Benefits are normalized into chunks with citations in `core/ingestion.py`.
3. `core/retriever.py` loads or builds FAISS indexes under `faiss_index/<plan_id>/`.
4. `backend/service.py` routes chat turns to:
   - `workflows/claim_workflow.py` for claim drafting
   - `workflows/appointment_workflow.py` for appointment booking
   - `core/llm.py` for coverage Q and A and plan-overview responses
5. Claim confirmations generate a PDF in `generated_claims/`.

## Requirements

- Python 3.11 recommended
- Node.js 20+
- `pip`
- `npm`

## Environment Variables

Set these in `.env` (example values are in `.env.example`):

- `GEMINI_API_KEY`
- `EMBEDDING_MODEL` (default: `all-MiniLM-L6-v2`)
- `ENABLE_GEMINI_ANSWER_GENERATION` (`true` or `false`)
- `GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `GEMINI_TEMPERATURE`
- `GEMINI_MAX_OUTPUT_TOKENS`
- `BACKEND_HOST`
- `BACKEND_PORT`

## Local Development

### 1) Install backend dependencies

```bash
pip install -r requirements.txt
```

### 2) Run the API

```bash
uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

### 3) Install frontend dependencies

```bash
cd frontend
npm ci
```

On PowerShell, if script execution blocks npm:

```powershell
cd frontend
npm.cmd ci
```

### 4) Run the frontend

```bash
cd frontend
npm run dev
```

Open:

- UI: `http://127.0.0.1:3000`
- API docs: `http://127.0.0.1:8000/docs`
- API health: `http://127.0.0.1:8000/health`

## Docker

Run backend and frontend together:

```bash
docker compose up --build
```

This starts:

- API on `:8000`
- Frontend on `:3000`

The frontend container uses `BACKEND_API_BASE_URL=http://api:8000`.

## API Endpoints

- `GET /`
- `GET /health`
- `GET /plans`
- `GET /plans/{plan_id}`
- `POST /plans/{plan_id}/rebuild`
- `POST /chat`
- `POST /sessions/{session_id}/reset`

Example:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"plan_id\":\"4d_health_5\",\"message\":\"Does my insurance cover MRI?\"}"
```

## Claim Workflow

Start with a message like:

```text
I want to file a claim for physiotherapy
```

Current claim flow:

1. Treatment
2. Date of service (`DD/MM/YYYY`)
3. Amount in EUR
4. Receipt confirmation (`yes/no`)
5. Final confirmation (`yes/no`)
6. Generate claim PDF

If the entered amount exceeds an extracted plan limit (for example `EUR 30 x 9 visits`), the bot shows a warning and asks whether to continue.

On successful confirmation, PDF output is saved to:

- `generated_claims/claim_<timestamp>.pdf`

## Appointment Workflow

Users can also book an appointment flow (for example physiotherapy) with guided prompts for:

- Treatment type
- Date of birth
- Mode (in-person or virtual)
- Date and time preferences
- Final confirmation

## Retrieval and Indexing Notes

- Index path: `faiss_index/<plan_id>/`
- Index artifacts:
  - `index.faiss`
  - `chunks.json`
  - `manifest.json`
- Rebuild triggers include source data or model/version changes.
- If vector retrieval is unavailable, the app falls back to keyword matching.

## Troubleshooting

`Frontend cannot reach backend`

- Confirm API is running at `http://127.0.0.1:8000/health`
- Confirm frontend is running at `http://127.0.0.1:3000`

`PowerShell blocks npm`

- Use `npm.cmd` instead of `npm`

`vector_enabled` is false

- Reinstall Python dependencies
- Confirm Python 3.11 is used
- Rebuild the selected plan index

`Python entrypoint confusion`

- `main.py` only prints startup guidance
- Start services with `uvicorn` (API) and `npm run dev` (frontend)

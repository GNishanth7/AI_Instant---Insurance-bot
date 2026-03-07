# Health Insurance Plan Assistant

Local-first health insurance assistant built around the `4d_health_*.json` plan files in this repo. The backend stays in FastAPI, while the frontend is now a dedicated Next.js app with a more polished, product-style interface inspired by `kota.io`: warm neutrals, deep green surfaces, rounded cards, clearer hierarchy, and clickable workflow actions.

Policy data is not sent to external APIs during retrieval or answer generation.

## Stack

- FastAPI backend in [backend/server.py](/E:/Give_a_go/backend/server.py)
- Next.js frontend in [frontend/](/E:/Give_a_go/frontend)
- Local `sentence-transformers` embeddings
- FAISS vector search
- Deterministic answer formatting and claim workflow

## What It Does

- Auto-discovers plan files matching `4d_health_*.json`
- Normalizes each benefit row into searchable chunks with citations
- Builds a local FAISS index per plan under `faiss_index/<plan_id>/`
- Answers coverage questions against the selected plan
- Returns citations in the form `Category > Section > Benefit (source_file.json)`
- Supports a guided claim draft flow
- Exposes a FastAPI API and a professional frontend

## Architecture

1. [core/ingestion.py](/E:/Give_a_go/core/ingestion.py) loads and normalizes plan JSON into `PolicyChunk` records.
2. [core/retriever.py](/E:/Give_a_go/core/retriever.py) creates local embeddings with `all-MiniLM-L6-v2` and searches them with `faiss-cpu`.
3. [core/llm.py](/E:/Give_a_go/core/llm.py) formats answers locally. There is no remote LLM call.
4. [workflows/claim_workflow.py](/E:/Give_a_go/workflows/claim_workflow.py) runs the deterministic claim flow.
5. [backend/server.py](/E:/Give_a_go/backend/server.py) exposes the API.
6. [frontend/app/page.tsx](/E:/Give_a_go/frontend/app/page.tsx) renders the Next.js UI.
7. [frontend/app/api/[...path]/route.ts](/E:/Give_a_go/frontend/app/api/[...path]/route.ts) proxies browser requests to FastAPI so the frontend can talk to a single app origin.

## Privacy

- Policy content stays on the machine during indexing, retrieval, and answer generation.
- The first `sentence-transformers` run may download the `all-MiniLM-L6-v2` model if it is not already cached.
- After the model is cached, plan processing stays local.

## Requirements

- Python 3.11 recommended for the backend
- Node.js 20+ recommended for the frontend
- `pip`
- `npm`

`faiss-cpu==1.8.0` was verified with Python 3.11 in this project. If your default `python` points to 3.13, use Python 3.11 explicitly instead.


## Project Layout

```text
backend/         FastAPI app, schemas, and service layer
core/            Ingestion, retrieval, and deterministic answer formatting
frontend/        Next.js UI and API proxy
workflows/       Claim workflow state machine
faiss_index/     Generated local vector indexes and chunk manifests
4d_health_*.json Plan data files
Dockerfile       Backend container
docker-compose.yml Combined API + frontend setup
```

## Backend Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Run the API:

```bash
uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

## Frontend Setup

Install frontend dependencies:

```bash
cd frontend
npm ci
```

If PowerShell blocks `npm.ps1`, use `npm.cmd` instead:

```powershell
cd frontend
npm.cmd ci
```

Run the Next.js app:

```bash
cd frontend
npm run dev
```

Open:

- API health: `http://127.0.0.1:8000/health`
- API docs: `http://127.0.0.1:8000/docs`
- Frontend UI: `http://127.0.0.1:3000`

## Docker

To run both services with Docker Compose:

```bash
docker compose up --build
```

This starts:

- FastAPI on port `8000`
- Next.js on port `3000`

Container notes:

- `.dockerignore` excludes `faiss_index/`, so containers start without prebuilt indexes.
- Indexes are created inside the backend container on first use or when you trigger a rebuild.
- `frontend/` has its own Dockerfile and proxies API calls server-side to `http://api:8000`.

## How Indexing Works

- A plan index is stored under `faiss_index/<plan_id>/`
- Each index includes:
  - `index.faiss`
  - `chunks.json`
  - `manifest.json`
- The retriever rebuilds automatically when:
  - the source JSON file changed
  - the embedding model changed
  - the internal `INDEX_VERSION` changed
- If embedding or FAISS loading fails, the app falls back to keyword-only retrieval and the plan reports `vector_enabled: false`

## API Endpoints

- `GET /`
- `GET /health`
- `GET /plans`
- `GET /plans/{plan_id}`
- `POST /plans/{plan_id}/rebuild`
- `POST /chat`
- `POST /sessions/{session_id}/reset`

Example question:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"plan_id\":\"4d_health_5\",\"message\":\"Does my insurance cover MRI?\"}"
```

## UI Notes

The new frontend intentionally moves away from the old Streamlit look. The current design direction is:

- Kota-style visual language: green foundation, warm paper tones, soft gradients, rounded surfaces
- three-panel workspace layout on desktop
- quick replies for simple workflow decisions like `Yes`, `No`, and `Cancel`
- side rail for sources and claim status
- a more product-like interaction model than raw chat bubbles alone

## Claim Draft Flow

Start with a message such as:

```text
I want to file a claim for physiotherapy
```

The workflow then asks for:

1. treatment type
2. date of service in `DD/MM/YYYY`
3. amount in EUR
4. whether a receipt exists
5. final confirmation

When the step is a binary decision, the frontend surfaces clickable quick replies instead of forcing manual typing.

## Troubleshooting

`Frontend cannot reach the backend`

- Start FastAPI first on `127.0.0.1:8000`
- Confirm `http://127.0.0.1:8000/health` responds
- In Docker, confirm the frontend container has `BACKEND_API_BASE_URL=http://api:8000`

`PowerShell blocks npm`

- Use `npm.cmd` instead of `npm`

`vector_enabled` is `false`

- Confirm backend dependencies installed successfully from [requirements.txt](/E:/Give_a_go/requirements.txt)
- Make sure Python 3.11 is being used
- Rebuild the selected plan index

`The plan data changed but answers did not`

- Rebuild the plan index
- The retriever uses file modification time and manifest metadata to decide when to rebuild

`python` points to the wrong interpreter

- Use Python 3.11 explicitly
- [main.py](/E:/Give_a_go/main.py) only prints the recommended startup commands

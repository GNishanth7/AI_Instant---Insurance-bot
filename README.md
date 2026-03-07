# Health Insurance Plan Assistant

Local-first health insurance assistant built around the `4d_health_*.json` plan files in this repo. It provides a FastAPI backend, a Streamlit chat UI, local semantic retrieval with `sentence-transformers` + FAISS, deterministic answer formatting, and a guided claim draft flow.

Policy data is not sent to external APIs during retrieval or answer generation.

## What It Does

- Auto-discovers plan files matching `4d_health_*.json`.
- Normalizes each benefit row into searchable chunks with citations.
- Builds a local FAISS index per plan under `faiss_index/<plan_id>/`.
- Answers coverage questions against the selected plan.
- Returns citations in the form `Category > Section > Benefit (source_file.json)`.
- Supports a guided claim draft flow in chat.
- Exposes a FastAPI API and Swagger docs.

## Architecture

1. `core/ingestion.py` loads and normalizes plan JSON into `PolicyChunk` records.
2. `core/retriever.py` creates local embeddings with `all-MiniLM-L6-v2` and searches them with `faiss-cpu`.
3. `core/llm.py` formats answers locally. Despite the file name, there is no remote LLM call.
4. `workflows/claim_workflow.py` runs a deterministic, step-based claim flow.
5. `backend/server.py` exposes the API.
6. `app.py` is a Streamlit client for the backend.

## Privacy

- Policy content stays on the machine during indexing, retrieval, and answer generation.
- The first `sentence-transformers` run may download the `all-MiniLM-L6-v2` model if it is not already cached.
- After the model is cached, plan processing stays local.

## Requirements

- Python 3.11 recommended
- `pip`
- Enough local disk space for the Python dependencies and the cached embedding model

`faiss-cpu==1.8.0` was verified with Python 3.11 in this project. If your default `python` points to 3.13, use Python 3.11 explicitly instead.

On the machine where this repo was last verified, the working interpreter was:

```text
C:\Users\nisha\AppData\Local\Programs\Python\Python311\python.exe
```

## Project Layout

```text
backend/        FastAPI app, schemas, and service layer
core/           Ingestion, retrieval, and deterministic answer formatting
workflows/      Claim workflow state machine
app.py          Streamlit UI
client.py       HTTP client used by the UI
config.py       Runtime configuration
faiss_index/    Generated local vector indexes and chunk manifests
4d_health_*.json Plan data files
```

## Local Setup

Make sure `python --version` shows Python 3.11 before installing dependencies.

```bash
pip install -r requirements.txt
```

If your machine has multiple Python versions, use Python 3.11 explicitly:

```powershell
& 'C:\Users\nisha\AppData\Local\Programs\Python\Python311\python.exe' -m pip install -r requirements.txt
```

## Run The App

Start the API in one terminal:

```bash
uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

Start the UI in another terminal:

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

If you need the verified Python 3.11 executables directly on Windows:

```powershell
& 'C:\Users\nisha\AppData\Local\Programs\Python\Python311\Scripts\uvicorn.exe' backend.server:app --host 127.0.0.1 --port 8000
& 'C:\Users\nisha\AppData\Local\Programs\Python\Python311\Scripts\streamlit.exe' run app.py --server.address 127.0.0.1 --server.port 8501
```

Open:

- API health: `http://127.0.0.1:8000/health`
- API docs: `http://127.0.0.1:8000/docs`
- Streamlit UI: `http://127.0.0.1:8501`

## Docker

To run both services with Docker Compose:

```bash
docker compose up --build
```

This starts:

- FastAPI on port `8000`
- Streamlit on port `8501`

Current container notes:

- `.dockerignore` excludes `faiss_index/`, so containers start without prebuilt indexes.
- Indexes are created inside the container on first use or when you trigger a rebuild.
- The current `docker-compose.yml` does not mount a volume for `faiss_index/`, so indexes are not persisted across container rebuilds.

## How Indexing Works

- A plan index is stored under `faiss_index/<plan_id>/`.
- Each index includes:
  - `index.faiss`
  - `chunks.json`
  - `manifest.json`
- The retriever rebuilds automatically when:
  - the source JSON file changed
  - the embedding model changed
  - the internal `INDEX_VERSION` changed
- If embedding or FAISS loading fails, the app falls back to keyword-only retrieval and the plan will report `vector_enabled: false`.

## API Endpoints

- `GET /`
- `GET /health`
- `GET /plans`
- `GET /plans/{plan_id}`
- `POST /plans/{plan_id}/rebuild`
- `POST /chat`
- `POST /sessions/{session_id}/reset`

Example plan listing:

```bash
curl http://127.0.0.1:8000/plans
```

Example question:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"plan_id\":\"4d_health_5\",\"message\":\"Does my insurance cover MRI?\"}"
```

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

If coverage is confirmed, the assistant returns a JSON claim summary with the matched coverage source.

## Configuration

Key values live in `config.py`. Useful overrides:

- `API_BASE_URL`
- `EMBEDDING_MODEL`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `UI_PORT`
- `MIN_REQUEST_GAP_SECONDS`

`.env` loading is supported through `python-dotenv`, but an API key is not required for the current local-only stack.

## Troubleshooting

`Streamlit says the backend is unreachable`

- Start `uvicorn backend.server:app --host 127.0.0.1 --port 8000`.
- Confirm `http://127.0.0.1:8000/health` responds.
- Check that `API_BASE_URL` points to the running backend.

`vector_enabled` is `false`

- Confirm dependencies installed successfully from `requirements.txt`.
- Make sure Python 3.11 is being used.
- Rebuild the selected plan index from the sidebar or call `POST /plans/{plan_id}/rebuild`.

`The plan data changed but answers did not`

- Rebuild the plan index.
- The retriever uses file modification time and manifest metadata to decide when to rebuild.

`python` points to the wrong interpreter

- Use Python 3.11 explicitly.
- `main.py` is not the application entrypoint; it only prints the correct startup commands.

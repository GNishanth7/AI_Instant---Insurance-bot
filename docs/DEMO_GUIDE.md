# Product Demo Guide

This guide is a ready-to-run script for demonstrating the Health Insurance Plan Assistant.

## Demo Goal

Show that the product can:

- Answer policy coverage questions with citations
- Guide users through claim drafting
- Warn when claim amount exceeds a plan limit
- Generate a professional claim PDF for submission
- Guide users through appointment booking

## Demo Duration

- Full demo: 10 to 15 minutes
- Quick demo: 5 to 7 minutes

## Pre-Demo Checklist

1. Open a terminal at project root.
2. Install backend dependencies.
3. Install frontend dependencies.
4. Start backend and frontend.
5. Open the app and pre-select a plan.
6. Keep `generated_claims/` open in file explorer for quick PDF verification.

## One-Time Setup

### Backend

```bash
pip install -r requirements.txt
uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

PowerShell fallback if npm scripts are blocked:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

## URLs During Demo

- Product UI: `http://127.0.0.1:3000`
- API docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## Suggested Demo Script

## 1) Open and Position the Product (1 minute)

Say:

"This assistant is connected to our health plan files and can answer coverage questions, draft claims, and generate claim PDFs."

Do:

1. Open UI at `http://127.0.0.1:3000`.
2. Select any plan file and continue.
3. Point out the 3-panel workspace: conversation, sources, workflow context.

## 2) Coverage Q&A with Source Traceability (2 minutes)

Type:

```text
Does my insurance cover MRI?
```

Expected outcome:

- Assistant gives a policy-grounded answer.
- Citation appears in response.
- Sources panel shows top matching policy chunks.

Say:

"Every answer is grounded in policy chunks, and you can inspect source citations in real time."

## 3) Plan Overview Capability (1 to 2 minutes)

Type:

```text
Give me an overview of my plan
```

Expected outcome:

- Assistant returns a summarized overview of major cover areas.
- Quick replies update for next follow-up questions.

## 4) Claim Workflow with Limit Warning and PDF Generation (4 minutes)

Type:

```text
I want to file a claim for physiotherapy
```

Follow prompts with:

1. Date: `14/06/2025`
2. Amount: `1700`
3. Continue after warning: `yes`
4. Receipt: `yes`
5. Final confirmation: `yes`

Expected outcome:

- Assistant warns that the amount exceeds extracted benefit limits.
- Assistant still allows continuation.
- On final confirmation, assistant returns a success message with PDF save path.
- PDF is created under `generated_claims/claim_<timestamp>.pdf`.

Say:

"The workflow is deterministic, policy-aware, and generates a submission-ready claim PDF."

Optional proof step:

1. Open the latest file in `generated_claims/`.
2. Show header, submitted date, claim table, and policy source.

## 5) Appointment Workflow (2 minutes)

Type:

```text
I want to book a physiotherapy appointment
```

Follow prompts with example values:

1. Date of birth: `01/01/1995`
2. Mode: `In-person`
3. Preferred date: `20/06/2025`
4. Time window: `Morning`
5. Location: `Dublin`
6. Confirm: `yes`

Expected outcome:

- Assistant collects required details step-by-step.
- Workflow summary appears in context panel.

## Quick Demo Version (5 to 7 minutes)

If time is short, only do:

1. One coverage question (`Does my insurance cover MRI?`)
2. Claim workflow through PDF generation
3. Show generated PDF file in `generated_claims/`

## Recovery Plan During Live Demo

If something goes wrong:

1. Click `Reset Chat` in UI.
2. Re-select plan if needed.
3. Retry with one of these starter prompts:
   - `Does my insurance cover MRI?`
   - `I want to file a claim for physiotherapy`
   - `I want to book a physiotherapy appointment`

## Post-Demo Talking Points

- Local retrieval and citation-backed answers
- Guided workflows reduce user input errors
- Built-in claim amount limit warning
- Claim PDF generated instantly for handoff
- API-first design with a modern frontend

## Notes for Presenter

- Keep answers short and business-focused.
- Always show one source citation to build trust.
- During claim flow, intentionally trigger the over-limit warning once.
- End by showing the generated PDF to make the value tangible.

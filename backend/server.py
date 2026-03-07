from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    PlanDetail,
    PlanSummary,
    RebuildResponse,
    ResetSessionResponse,
)
from backend.service import PolicyBackendService, RateLimitError, UnknownPlanError
from config import APP_NAME, APP_VERSION

service = PolicyBackendService()
app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=HealthResponse)
def root() -> HealthResponse:
    return HealthResponse(status="ok", app_name=APP_NAME, version=APP_VERSION)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app_name=APP_NAME, version=APP_VERSION)


@app.get("/plans", response_model=list[PlanSummary])
def list_plans() -> list[PlanSummary]:
    return [PlanSummary(**plan) for plan in service.list_plans()]


@app.get("/plans/{plan_id}", response_model=PlanDetail)
def get_plan(plan_id: str) -> PlanDetail:
    try:
        return PlanDetail(**service.get_plan_detail(plan_id))
    except UnknownPlanError as exc:
        raise HTTPException(status_code=404, detail="Unknown plan.") from exc


@app.post("/plans/{plan_id}/rebuild", response_model=RebuildResponse)
def rebuild_plan(plan_id: str) -> RebuildResponse:
    try:
        return RebuildResponse(**service.rebuild_plan_index(plan_id))
    except UnknownPlanError as exc:
        raise HTTPException(status_code=404, detail="Unknown plan.") from exc


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        payload = service.handle_chat(
            plan_id=request.plan_id,
            message=request.message,
            session_id=request.session_id,
        )
        return ChatResponse(**payload)
    except UnknownPlanError as exc:
        raise HTTPException(status_code=404, detail="Unknown plan.") from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/reset", response_model=ResetSessionResponse)
def reset_session(session_id: str) -> ResetSessionResponse:
    return ResetSessionResponse(**service.reset_session(session_id))

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str


class PlanSummary(BaseModel):
    id: str
    display_name: str
    source_file: str
    benefit_count: int
    category_count: int
    section_count: int


class PlanDetail(PlanSummary):
    vector_enabled: bool
    ai_generation_enabled: bool


class SourceItem(BaseModel):
    citation: str
    benefit: str
    coverage: str
    score: float


class ChatRequest(BaseModel):
    plan_id: str
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    plan_id: str
    content: str
    citation: str = ""
    sources: list[SourceItem] = Field(default_factory=list)
    claim_summary: dict[str, Any] | None = None
    appointment_summary: dict[str, Any] | None = None
    disclaimer: str = ""
    quick_replies: list[str] = Field(default_factory=list)
    input_mode: str = "text"
    input_context: str = ""


class RebuildResponse(BaseModel):
    plan_id: str
    rebuilt: bool
    vector_enabled: bool


class ResetSessionResponse(BaseModel):
    session_id: str
    reset: bool

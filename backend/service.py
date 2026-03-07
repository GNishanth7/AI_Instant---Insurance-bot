from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from uuid import uuid4

from config import (
    ANSWER_DISCLAIMER,
    MAX_QUESTION_LENGTH,
    MIN_REQUEST_GAP_SECONDS,
    NOT_FOUND_MESSAGE,
    PROMPT_INJECTION_PATTERNS,
    RATE_LIMIT_MESSAGE,
    STARTER_QUICK_REPLIES,
    SESSION_TTL_SECONDS,
)
from core.ingestion import discover_plan_files, load_plan_chunks, summarize_plan
from core.llm import PolicyAssistantLLM
from core.retriever import PlanRetriever
from workflows.claim_workflow import handle_claim_turn, initial_claim_state, is_claim_intent


class UnknownPlanError(KeyError):
    pass


class RateLimitError(RuntimeError):
    pass


@dataclass(slots=True)
class ChatSession:
    session_id: str
    plan_id: str
    claim_state: dict = field(default_factory=initial_claim_state)
    last_request_at: float = 0.0
    updated_at: float = field(default_factory=time.time)


class PolicyBackendService:
    def __init__(self) -> None:
        self._lock = RLock()
        self._retrievers: dict[str, PlanRetriever] = {}
        self._plan_cache: dict[str, dict] = {}
        self._plan_paths: dict[str, Path] = {}
        self._sessions: dict[str, ChatSession] = {}
        self._assistant = PolicyAssistantLLM()

    def list_plans(self) -> list[dict]:
        with self._lock:
            self._refresh_plan_paths()
            return [self._plan_summary(plan_id) for plan_id in sorted(self._plan_paths)]

    def get_plan_detail(self, plan_id: str) -> dict:
        with self._lock:
            summary = self._plan_summary(plan_id)
            retriever = self._get_retriever(plan_id)
            stats = retriever.plan_stats()
            return {
                **summary,
                "vector_enabled": bool(stats["vector_enabled"]),
            }

    def rebuild_plan_index(self, plan_id: str) -> dict:
        with self._lock:
            retriever = self._get_retriever(plan_id)
            retriever.rebuild()
            stats = retriever.plan_stats()
            return {
                "plan_id": plan_id,
                "rebuilt": True,
                "vector_enabled": bool(stats["vector_enabled"]),
            }

    def reset_session(self, session_id: str) -> dict:
        with self._lock:
            self._sessions.pop(session_id, None)
        return {"session_id": session_id, "reset": True}

    def handle_chat(self, plan_id: str, message: str, session_id: str | None = None) -> dict:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Please enter a question.")
        if len(cleaned_message) > MAX_QUESTION_LENGTH:
            raise ValueError(f"Questions must be {MAX_QUESTION_LENGTH} characters or fewer.")

        with self._lock:
            self._cleanup_sessions()
            session = self._get_or_create_session(session_id=session_id, plan_id=plan_id)
            self._enforce_rate_limit(session)
            self._log_suspicious_input(cleaned_message)

            retriever = self._get_retriever(plan_id)
            if session.claim_state.get("active") or is_claim_intent(cleaned_message):
                result = handle_claim_turn(
                    cleaned_message,
                    session.claim_state,
                    retriever,
                    self._assistant,
                )
                response = {
                    "session_id": session.session_id,
                    "plan_id": plan_id,
                    "content": result.message,
                    "citation": result.citation,
                    "sources": result.sources,
                    "claim_summary": result.claim_summary,
                    "disclaimer": ANSWER_DISCLAIMER if result.citation else "",
                    "quick_replies": self._quick_replies_for_session(session),
                }
            else:
                retrieval_results = retriever.retrieve(cleaned_message)
                relevant_match = retriever.has_relevant_match(retrieval_results)
                answer = self._assistant.answer_question(
                    cleaned_message,
                    retrieval_results,
                    relevant_match,
                )
                response = {
                    "session_id": session.session_id,
                    "plan_id": plan_id,
                    "content": answer.answer or NOT_FOUND_MESSAGE,
                    "citation": answer.citation,
                    "sources": answer.sources,
                    "claim_summary": None,
                    "disclaimer": answer.disclaimer if answer.citation else "",
                    "quick_replies": list(STARTER_QUICK_REPLIES),
                }

            session.last_request_at = time.time()
            session.updated_at = session.last_request_at
            return response

    def _refresh_plan_paths(self) -> None:
        discovered = discover_plan_files()
        self._plan_paths = {path.stem: path for path in discovered}

    def _plan_summary(self, plan_id: str) -> dict:
        self._refresh_plan_paths()
        plan_path = self._plan_paths.get(plan_id)
        if plan_path is None:
            raise UnknownPlanError(plan_id)

        if plan_id not in self._plan_cache:
            chunks = load_plan_chunks(plan_path)
            summary = summarize_plan(chunks)
            self._plan_cache[plan_id] = {
                "id": plan_id,
                "display_name": plan_path.name,
                "source_file": plan_path.name,
                "benefit_count": summary["benefit_count"],
                "category_count": summary["category_count"],
                "section_count": summary["section_count"],
            }

        return self._plan_cache[plan_id]

    def _get_retriever(self, plan_id: str) -> PlanRetriever:
        self._refresh_plan_paths()
        plan_path = self._plan_paths.get(plan_id)
        if plan_path is None:
            raise UnknownPlanError(plan_id)

        if plan_id not in self._retrievers:
            retriever = PlanRetriever(plan_path)
            retriever.ensure_index()
            self._retrievers[plan_id] = retriever

        return self._retrievers[plan_id]

    def _get_or_create_session(self, session_id: str | None, plan_id: str) -> ChatSession:
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            if session.plan_id != plan_id:
                session.plan_id = plan_id
                session.claim_state = initial_claim_state()
                session.last_request_at = 0.0
            return session

        new_session = ChatSession(
            session_id=session_id or str(uuid4()),
            plan_id=plan_id,
        )
        self._sessions[new_session.session_id] = new_session
        return new_session

    def _cleanup_sessions(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.updated_at < cutoff
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def _enforce_rate_limit(self, session: ChatSession) -> None:
        elapsed = time.time() - session.last_request_at
        if 0 < elapsed < MIN_REQUEST_GAP_SECONDS:
            raise RateLimitError(RATE_LIMIT_MESSAGE)

    @staticmethod
    def _log_suspicious_input(message: str) -> None:
        lowered = message.lower()
        if any(pattern in lowered for pattern in PROMPT_INJECTION_PATTERNS) or len(message) > 300:
            print(f"[suspicious-input] {message}")

    @staticmethod
    def _quick_replies_for_session(session: ChatSession) -> list[str]:
        if not session.claim_state.get("active"):
            return list(STARTER_QUICK_REPLIES)

        step = session.claim_state.get("step", "idle")
        if step == "awaiting_treatment":
            return ["Physiotherapy", "MRI", "Dental", "Cancel"]
        if step == "awaiting_receipt":
            return ["Yes", "No", "Cancel"]
        if step == "awaiting_confirmation":
            return ["Yes", "No"]
        if step in {"awaiting_date", "awaiting_amount"}:
            return ["Cancel"]
        return list(STARTER_QUICK_REPLIES)

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
    PLAN_OVERVIEW_QUICK_REPLIES,
    PROMPT_INJECTION_PATTERNS,
    RATE_LIMIT_MESSAGE,
    STARTER_QUICK_REPLIES,
    SESSION_TTL_SECONDS,
)
from core.ingestion import (
    build_plan_overview_context,
    discover_plan_files,
    load_plan_chunks,
    summarize_plan,
)
from core.llm import PolicyAssistantLLM
from core.retriever import PlanRetriever
from workflows.appointment_workflow import (
    handle_appointment_turn,
    initial_appointment_state,
    is_appointment_intent,
)
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
    appointment_state: dict = field(default_factory=initial_appointment_state)
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
                "ai_generation_enabled": self._assistant.ai_generation_enabled,
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
            controls = self._response_controls_for_session(session)
            if session.appointment_state.get("active") or is_appointment_intent(cleaned_message):
                result = handle_appointment_turn(
                    cleaned_message,
                    session.appointment_state,
                    retriever,
                    self._assistant,
                )
                controls = self._response_controls_for_session(session)
                response = {
                    "session_id": session.session_id,
                    "plan_id": plan_id,
                    "content": result.message,
                    "citation": result.citation,
                    "sources": result.sources,
                    "claim_summary": None,
                    "appointment_summary": result.appointment_summary,
                    "disclaimer": ANSWER_DISCLAIMER if result.citation else "",
                    "quick_replies": controls["quick_replies"],
                    "input_mode": controls["input_mode"],
                    "input_context": controls["input_context"],
                }
            elif session.claim_state.get("active") or is_claim_intent(cleaned_message):
                result = handle_claim_turn(
                    cleaned_message,
                    session.claim_state,
                    retriever,
                    self._assistant,
                )
                controls = self._response_controls_for_session(session)
                response = {
                    "session_id": session.session_id,
                    "plan_id": plan_id,
                    "content": result.message,
                    "citation": result.citation,
                    "sources": result.sources,
                    "claim_summary": result.claim_summary,
                    "appointment_summary": None,
                    "disclaimer": ANSWER_DISCLAIMER if result.citation else "",
                    "quick_replies": controls["quick_replies"],
                    "input_mode": controls["input_mode"],
                    "input_context": controls["input_context"],
                }
            elif self._is_plan_overview_intent(cleaned_message):
                plan_summary = self._plan_summary(plan_id)
                overview_context = build_plan_overview_context(retriever.chunks)
                answer = self._assistant.answer_plan_overview(
                    question=cleaned_message,
                    plan_name=plan_summary["display_name"],
                    overview_context=overview_context,
                )
                response = {
                    "session_id": session.session_id,
                    "plan_id": plan_id,
                    "content": answer.answer or NOT_FOUND_MESSAGE,
                    "citation": answer.citation,
                    "sources": answer.sources,
                    "claim_summary": None,
                    "appointment_summary": None,
                    "disclaimer": answer.disclaimer if answer.citation else "",
                    "quick_replies": list(PLAN_OVERVIEW_QUICK_REPLIES),
                    "input_mode": "text",
                    "input_context": "plan_overview",
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
                    "appointment_summary": None,
                    "disclaimer": answer.disclaimer if answer.citation else "",
                    "quick_replies": controls["quick_replies"],
                    "input_mode": controls["input_mode"],
                    "input_context": controls["input_context"],
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
                session.appointment_state = initial_appointment_state()
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
    def _is_plan_overview_intent(message: str) -> bool:
        normalized = " ".join(message.lower().strip().split())
        direct_phrases = [
            "what does my insurance cover",
            "what my insurance covers",
            "what does my plan cover",
            "what does this plan cover",
            "what is covered by my insurance",
            "what is covered in my plan",
            "give me an overview of my plan",
            "give me a plan overview",
            "explain my plan",
            "explain my insurance",
            "help me understand my plan",
            "help me understand my insurance",
            "learn what my insurance covers",
            "how can i use my insurance",
            "how do i use my insurance",
            "how can i make use of it",
            "what can i use it for",
        ]
        if any(phrase in normalized for phrase in direct_phrases):
            return True

        broad_markers = {"overview", "summary", "explain", "understand", "learn"}
        plan_markers = {"insurance", "plan", "policy", "benefits", "benefit"}
        cover_markers = {"cover", "covers", "covered"}

        tokens = set(normalized.split())
        if broad_markers & tokens and (plan_markers & tokens or cover_markers & tokens):
            return True

        return (
            "how can i use" in normalized
            and ("insurance" in tokens or "plan" in tokens or "policy" in tokens)
        )

    @staticmethod
    def _response_controls_for_session(session: ChatSession) -> dict[str, str | list[str]]:
        if session.appointment_state.get("active"):
            step = session.appointment_state.get("step", "idle")
            if step == "awaiting_treatment":
                return {
                    "quick_replies": ["Physiotherapy", "MRI", "Dental", "Cancel"],
                    "input_mode": "text",
                    "input_context": "appointment_type",
                }
            if step == "awaiting_date_of_birth":
                return {
                    "quick_replies": ["Cancel"],
                    "input_mode": "date",
                    "input_context": "date_of_birth",
                }
            if step == "awaiting_mode":
                return {
                    "quick_replies": ["In-person", "Virtual", "No preference", "Cancel"],
                    "input_mode": "text",
                    "input_context": "appointment_mode",
                }
            if step == "awaiting_time_window":
                return {
                    "quick_replies": ["Morning", "Afternoon", "Evening", "Cancel"],
                    "input_mode": "text",
                    "input_context": "time_window",
                }
            if step == "awaiting_confirmation":
                return {
                    "quick_replies": ["Yes", "No"],
                    "input_mode": "text",
                    "input_context": "confirmation",
                }
            if step == "awaiting_date":
                return {
                    "quick_replies": ["Cancel"],
                    "input_mode": "date",
                    "input_context": "appointment_date",
                }
            if step == "awaiting_location":
                return {
                    "quick_replies": ["Cancel"],
                    "input_mode": "text",
                    "input_context": "location",
                }

        if not session.claim_state.get("active"):
            return {
                "quick_replies": list(STARTER_QUICK_REPLIES),
                "input_mode": "text",
                "input_context": "",
            }

        step = session.claim_state.get("step", "idle")
        if step == "awaiting_treatment":
            return {
                "quick_replies": ["Physiotherapy", "MRI", "Dental", "Cancel"],
                "input_mode": "text",
                "input_context": "claim_type",
            }
        if step == "awaiting_receipt":
            return {
                "quick_replies": ["Yes", "No", "Cancel"],
                "input_mode": "text",
                "input_context": "receipt",
            }
        if step == "awaiting_amount_warning_confirmation":
            return {
                "quick_replies": ["Yes", "No"],
                "input_mode": "text",
                "input_context": "amount_limit_confirmation",
            }
        if step == "awaiting_confirmation":
            return {
                "quick_replies": ["Yes", "No"],
                "input_mode": "text",
                "input_context": "confirmation",
            }
        if step == "awaiting_email":
            return {
                "quick_replies": ["Cancel"],
                "input_mode": "text",
                "input_context": "email",
            }
        if step == "awaiting_date":
            return {
                "quick_replies": ["Cancel"],
                "input_mode": "date",
                "input_context": "service_date",
            }
        if step == "awaiting_amount":
            return {
                "quick_replies": ["Cancel"],
                "input_mode": "text",
                "input_context": "amount",
            }
        return {
            "quick_replies": list(STARTER_QUICK_REPLIES),
            "input_mode": "text",
            "input_context": "",
        }

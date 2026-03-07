from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from config import APPOINTMENT_INTENT_KEYWORDS

_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_CANCEL_WORDS = {"cancel", "stop", "exit"}
_MODE_ALIASES = {
    "in-person": "In-person",
    "in person": "In-person",
    "onsite": "In-person",
    "virtual": "Virtual",
    "video": "Virtual",
    "online": "Virtual",
    "no preference": "No preference",
    "either": "No preference",
}
_TIME_WINDOW_ALIASES = {
    "morning": "Morning",
    "afternoon": "Afternoon",
    "evening": "Evening",
    "no preference": "No preference",
    "either": "No preference",
}


@dataclass(slots=True)
class AppointmentTurnResult:
    message: str
    citation: str = ""
    sources: list[dict[str, str | float]] = field(default_factory=list)
    appointment_summary: dict[str, Any] | None = None


def initial_appointment_state() -> dict[str, Any]:
    return {
        "active": False,
        "step": "idle",
        "data": {
            "appointment_type": "",
            "date_of_birth": "",
            "appointment_mode": "",
            "preferred_date": "",
            "preferred_time_window": "",
            "location": "",
            "policy_covered": None,
            "coverage_source": "",
            "coverage_details": "",
        },
    }


def is_appointment_intent(message: str) -> bool:
    normalized = message.lower()
    return any(keyword in normalized for keyword in APPOINTMENT_INTENT_KEYWORDS) or bool(
        re.search(
            r"\b(book|schedule|arrange)\b.*\b(appointment|consultation|visit)\b",
            normalized,
        )
    )


def extract_appointment_type_from_intent(message: str) -> str:
    normalized = " ".join(message.strip().split())
    patterns = [
        r"book (?:an )?appointment for (?P<treatment>.+)$",
        r"schedule (?:an )?appointment for (?P<treatment>.+)$",
        r"book (?:a )?(?P<treatment>.+?) appointment$",
        r"schedule (?:a )?(?P<treatment>.+?) appointment$",
        r"book (?:a )?(?P<treatment>.+?) consultation$",
        r"schedule (?:a )?(?P<treatment>.+?) consultation$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            return match.group("treatment").strip(" .")
    return ""


def handle_appointment_turn(message, state, retriever, assistant) -> AppointmentTurnResult:
    cleaned_message = message.strip()
    if cleaned_message.lower() in _CANCEL_WORDS:
        _reset_state(state)
        return AppointmentTurnResult(message="Appointment booking cancelled.")

    if not state.get("active"):
        state.update(initial_appointment_state())
        state["active"] = True
        state["step"] = "awaiting_treatment"
        extracted = extract_appointment_type_from_intent(cleaned_message)
        if extracted:
            return _store_treatment(extracted, state, retriever, assistant)
        return AppointmentTurnResult(message="What type of appointment would you like to book?")

    step = state.get("step", "idle")
    if step == "awaiting_treatment":
        return _store_treatment(cleaned_message, state, retriever, assistant)
    if step == "awaiting_date_of_birth":
        return _store_date_of_birth(cleaned_message, state)
    if step == "awaiting_mode":
        return _store_mode(cleaned_message, state)
    if step == "awaiting_date":
        return _store_date(cleaned_message, state)
    if step == "awaiting_time_window":
        return _store_time_window(cleaned_message, state)
    if step == "awaiting_location":
        return _store_location(cleaned_message, state)
    if step == "awaiting_confirmation":
        return _finalize_request(cleaned_message, state)

    _reset_state(state)
    return AppointmentTurnResult(message="Appointment booking was reset. Please start again.")


def _store_treatment(treatment, state, retriever, assistant) -> AppointmentTurnResult:
    results = retriever.retrieve(treatment)
    relevant = retriever.has_relevant_match(results)
    coverage = assistant.check_treatment_coverage(treatment, results, relevant)
    if coverage.status != "yes":
        _reset_state(state)
        return AppointmentTurnResult(
            message=(
                f"I could not confirm that {treatment} is covered in the selected policy data. "
                "Please try the exact benefit name or contact HR directly."
            ),
            citation=coverage.citation,
            sources=coverage.sources,
        )

    state["data"]["appointment_type"] = treatment.title()
    state["data"]["policy_covered"] = True
    state["data"]["coverage_source"] = coverage.citation
    state["data"]["coverage_details"] = coverage.summary
    state["step"] = "awaiting_date_of_birth"
    return AppointmentTurnResult(
        message=(
            f"{coverage.summary}\n\nWhat is the member's date of birth? Use DD/MM/YYYY."
        ),
        citation=coverage.citation,
        sources=coverage.sources,
    )


def _store_date_of_birth(value: str, state) -> AppointmentTurnResult:
    if not _DATE_PATTERN.fullmatch(value):
        return AppointmentTurnResult(message="Please enter the date of birth in DD/MM/YYYY format.")

    try:
        parsed_date = datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return AppointmentTurnResult(message="That date is not valid. Please use DD/MM/YYYY.")

    if parsed_date > datetime.today().date():
        return AppointmentTurnResult(
            message="Date of birth cannot be in the future."
        )

    state["data"]["date_of_birth"] = value
    state["step"] = "awaiting_mode"
    return AppointmentTurnResult(
        message=(
            "How would you like the appointment to be arranged: "
            "in-person, virtual, or no preference?"
        )
    )


def _store_mode(value: str, state) -> AppointmentTurnResult:
    normalized = _MODE_ALIASES.get(value.strip().lower())
    if normalized is None:
        return AppointmentTurnResult(
            message="Please choose in-person, virtual, or no preference."
        )

    state["data"]["appointment_mode"] = normalized
    state["step"] = "awaiting_date"
    return AppointmentTurnResult(
        message="What is your preferred appointment date? Use DD/MM/YYYY."
    )


def _store_date(value: str, state) -> AppointmentTurnResult:
    if not _DATE_PATTERN.fullmatch(value):
        return AppointmentTurnResult(message="Please enter the date in DD/MM/YYYY format.")

    try:
        parsed_date = datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return AppointmentTurnResult(message="That date is not valid. Please use DD/MM/YYYY.")

    if parsed_date < datetime.today().date():
        return AppointmentTurnResult(
            message="Please choose today or a future date for the appointment request."
        )

    state["data"]["preferred_date"] = value
    state["step"] = "awaiting_time_window"
    return AppointmentTurnResult(
        message="What time works best: morning, afternoon, evening, or no preference?"
    )


def _store_time_window(value: str, state) -> AppointmentTurnResult:
    normalized = _TIME_WINDOW_ALIASES.get(value.strip().lower())
    if normalized is None:
        return AppointmentTurnResult(
            message="Please choose morning, afternoon, evening, or no preference."
        )

    state["data"]["preferred_time_window"] = normalized
    state["step"] = "awaiting_location"
    return AppointmentTurnResult(
        message="Which city or location should the appointment be arranged near?"
    )


def _store_location(value: str, state) -> AppointmentTurnResult:
    cleaned = " ".join(value.strip().split())
    if len(cleaned) < 2:
        return AppointmentTurnResult(message="Please enter a city or location.")

    state["data"]["location"] = cleaned
    state["step"] = "awaiting_confirmation"
    summary = _appointment_summary(state["data"])
    return AppointmentTurnResult(
        message=(
            "Please confirm this appointment request by replying YES or NO. "
            "This creates a booking request draft, not a confirmed appointment."
        ),
        appointment_summary=summary,
    )


def _finalize_request(value: str, state) -> AppointmentTurnResult:
    normalized = value.strip().lower()
    if normalized in {"yes", "y"}:
        summary = _appointment_summary(state["data"])
        _reset_state(state)
        return AppointmentTurnResult(
            message=(
                "Appointment request draft generated. Share these details with your provider, "
                "insurer, or HR team to complete the booking."
            ),
            appointment_summary=summary,
            citation=summary["coverage_source"],
        )

    if normalized in {"no", "n"}:
        _reset_state(state)
        return AppointmentTurnResult(
            message="Appointment request discarded. Start again when ready."
        )

    return AppointmentTurnResult(message="Please reply YES to confirm or NO to discard the draft.")


def _appointment_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "appointment_type": data["appointment_type"],
        "date_of_birth": data["date_of_birth"],
        "appointment_mode": data["appointment_mode"],
        "preferred_date": data["preferred_date"],
        "preferred_time_window": data["preferred_time_window"],
        "location": data["location"],
        "policy_covered": data["policy_covered"],
        "coverage_source": data["coverage_source"],
        "coverage_details": data["coverage_details"],
    }


def _reset_state(state) -> None:
    state.clear()
    state.update(initial_appointment_state())

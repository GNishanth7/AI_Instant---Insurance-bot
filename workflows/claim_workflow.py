from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from config import CLAIM_INTENT_KEYWORDS

_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_CANCEL_WORDS = {"cancel", "stop", "exit"}


@dataclass(slots=True)
class ClaimTurnResult:
    message: str
    citation: str = ""
    sources: list[dict[str, str | float]] = field(default_factory=list)
    claim_summary: dict[str, Any] | None = None


def initial_claim_state() -> dict[str, Any]:
    return {
        "active": False,
        "step": "idle",
        "data": {
            "claim_type": "",
            "date_of_service": "",
            "amount_eur": None,
            "has_receipt": None,
            "policy_covered": None,
            "coverage_source": "",
            "coverage_details": "",
        },
    }


def is_claim_intent(message: str) -> bool:
    normalized = message.lower()
    return any(keyword in normalized for keyword in CLAIM_INTENT_KEYWORDS)


def extract_treatment_from_intent(message: str) -> str:
    normalized = " ".join(message.strip().split())
    patterns = [
        r"claim for (?P<treatment>.+)$",
        r"file a claim for (?P<treatment>.+)$",
        r"submit a claim for (?P<treatment>.+)$",
        r"make a claim for (?P<treatment>.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            return match.group("treatment").strip(" .")
    return ""


def handle_claim_turn(message, state, retriever, assistant) -> ClaimTurnResult:
    cleaned_message = message.strip()
    if cleaned_message.lower() in _CANCEL_WORDS:
        _reset_state(state)
        return ClaimTurnResult(message="Claim drafting cancelled.")

    if not state.get("active"):
        state.update(initial_claim_state())
        state["active"] = True
        state["step"] = "awaiting_treatment"
        extracted = extract_treatment_from_intent(cleaned_message)
        if extracted:
            return _store_treatment(extracted, state, retriever, assistant)
        return ClaimTurnResult(message="What treatment are you claiming for?")

    step = state.get("step", "idle")
    if step == "awaiting_treatment":
        return _store_treatment(cleaned_message, state, retriever, assistant)
    if step == "awaiting_date":
        return _store_date(cleaned_message, state)
    if step == "awaiting_amount":
        return _store_amount(cleaned_message, state)
    if step == "awaiting_receipt":
        return _store_receipt(cleaned_message, state)
    if step == "awaiting_confirmation":
        return _finalize_claim(cleaned_message, state)

    _reset_state(state)
    return ClaimTurnResult(message="Claim drafting was reset. Please start again.")


def _store_treatment(treatment, state, retriever, assistant) -> ClaimTurnResult:
    results = retriever.retrieve(treatment)
    relevant = retriever.has_relevant_match(results)
    coverage = assistant.check_treatment_coverage(treatment, results, relevant)
    if coverage.status != "yes":
        _reset_state(state)
        return ClaimTurnResult(
            message=(
                f"I could not confirm that {treatment} is covered in the selected policy data. "
                "Please try the exact benefit name or contact HR directly."
            ),
            citation=coverage.citation,
            sources=coverage.sources,
        )

    state["data"]["claim_type"] = treatment.title()
    state["data"]["policy_covered"] = True
    state["data"]["coverage_source"] = coverage.citation
    state["data"]["coverage_details"] = coverage.summary
    state["step"] = "awaiting_date"

    return ClaimTurnResult(
        message=f"{coverage.summary}\n\nPlease enter the date of service (DD/MM/YYYY).",
        citation=coverage.citation,
        sources=coverage.sources,
    )


def _store_date(value: str, state) -> ClaimTurnResult:
    if not _DATE_PATTERN.fullmatch(value):
        return ClaimTurnResult(message="Please enter the date in DD/MM/YYYY format.")

    try:
        datetime.strptime(value, "%d/%m/%Y")
    except ValueError:
        return ClaimTurnResult(message="That date is not valid. Please use DD/MM/YYYY.")

    state["data"]["date_of_service"] = value
    state["step"] = "awaiting_amount"
    return ClaimTurnResult(message="What is the claim amount in EUR?")


def _store_amount(value: str, state) -> ClaimTurnResult:
    cleaned = re.sub(r"[^0-9.]", "", value)
    if not cleaned or cleaned.count(".") > 1:
        return ClaimTurnResult(message="Please enter a valid amount, for example 120 or 120.50.")

    amount = float(cleaned)
    if amount <= 0:
        return ClaimTurnResult(message="Claim amount must be greater than zero.")

    state["data"]["amount_eur"] = round(amount, 2)
    state["step"] = "awaiting_receipt"
    return ClaimTurnResult(message="Do you have a receipt or invoice? Reply yes or no.")


def _store_receipt(value: str, state) -> ClaimTurnResult:
    normalized = value.strip().lower()
    if normalized in {"yes", "y"}:
        has_receipt = True
    elif normalized in {"no", "n"}:
        has_receipt = False
    else:
        return ClaimTurnResult(message="Please reply yes or no.")

    state["data"]["has_receipt"] = has_receipt
    state["step"] = "awaiting_confirmation"
    summary = _claim_summary(state["data"])
    return ClaimTurnResult(
        message="Please confirm these claim details by replying YES or NO.",
        claim_summary=summary,
    )


def _finalize_claim(value: str, state) -> ClaimTurnResult:
    normalized = value.strip().lower()
    if normalized in {"yes", "y"}:
        summary = _claim_summary(state["data"])
        _reset_state(state)
        return ClaimTurnResult(
            message="Claim summary generated.",
            claim_summary=summary,
            citation=summary["coverage_source"],
        )

    if normalized in {"no", "n"}:
        _reset_state(state)
        return ClaimTurnResult(message="Claim drafting discarded. Start again when ready.")

    return ClaimTurnResult(message="Please reply YES to confirm or NO to discard the draft.")


def _claim_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_type": data["claim_type"],
        "date_of_service": data["date_of_service"],
        "amount_eur": data["amount_eur"],
        "has_receipt": data["has_receipt"],
        "policy_covered": data["policy_covered"],
        "coverage_source": data["coverage_source"],
        "coverage_details": data["coverage_details"],
    }


def _reset_state(state) -> None:
    state.clear()
    state.update(initial_claim_state())

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from config import CLAIM_INTENT_KEYWORDS
from core.pdf_generator import generate_claim_pdf

_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_LIMIT_PATTERN = re.compile(
    r"((?:EUR|€)\s*\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?(?:\s+[A-Za-z]+)?)",
    re.IGNORECASE,
)
_SIMPLE_CAP_PATTERN = re.compile(
    r"(?:up to\s*)?((?:EUR|€)\s*\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_MULTIPLIER_VALUE_PATTERN = re.compile(
    r"(?:EUR|€)\s*(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_YES_WORDS = {"yes", "y"}
_NO_WORDS = {"no", "n"}
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
            "plan_id": "",
            "amount_limit_eur": None,
            "amount_limit_label": "",
            "pdf_file_path": "",
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
    if step == "awaiting_amount_warning_confirmation":
        return _confirm_limit_warning(cleaned_message, state)
    if step == "awaiting_receipt":
        return _store_receipt(cleaned_message, state)
    if step == "awaiting_confirmation":
        return _confirm_claim_summary(cleaned_message, state)

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

    coverage_details = getattr(coverage, "coverage_details", "") or coverage.summary
    state["data"]["claim_type"] = treatment.title()
    state["data"]["policy_covered"] = True
    state["data"]["coverage_source"] = coverage.citation
    state["data"]["coverage_details"] = coverage_details
    state["data"]["plan_id"] = getattr(retriever, "plan_name", "")
    state["data"]["amount_limit_eur"] = _extract_amount_limit_eur(coverage_details)
    state["data"]["amount_limit_label"] = _extract_amount_limit_label(coverage_details)
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

    rounded_amount = round(amount, 2)
    state["data"]["amount_eur"] = rounded_amount

    limit = state["data"].get("amount_limit_eur")
    limit_label = state["data"].get("amount_limit_label") or ""
    if limit is not None and rounded_amount > float(limit):
        state["step"] = "awaiting_amount_warning_confirmation"
        treatment = str(state["data"].get("claim_type", "this treatment")).lower()
        limit_text = _format_limit_reference(float(limit), limit_label)
        return ClaimTurnResult(
            message=(
                f"Note: Your plan covers {treatment} up to {limit_text}.\n"
                f"You have entered {_format_chat_currency(rounded_amount)} which exceeds this limit.\n"
                "Your claim may be partially reimbursed. Do you want to continue?"
            ),
            claim_summary=_claim_summary(state["data"]),
        )

    state["step"] = "awaiting_receipt"
    return ClaimTurnResult(message="Do you have a receipt or invoice? Reply yes or no.")


def _confirm_limit_warning(value: str, state) -> ClaimTurnResult:
    normalized = value.strip().lower()
    if normalized in _YES_WORDS:
        state["step"] = "awaiting_receipt"
        return ClaimTurnResult(message="Do you have a receipt or invoice? Reply yes or no.")

    if normalized in _NO_WORDS:
        state["data"]["amount_eur"] = None
        state["step"] = "awaiting_amount"
        return ClaimTurnResult(
            message="Okay. Please enter a different claim amount in EUR, or type Cancel."
        )

    return ClaimTurnResult(message="Please reply YES to continue or NO to change the amount.")


def _store_receipt(value: str, state) -> ClaimTurnResult:
    normalized = value.strip().lower()
    if normalized in _YES_WORDS:
        has_receipt = True
    elif normalized in _NO_WORDS:
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


def _confirm_claim_summary(value: str, state) -> ClaimTurnResult:
    normalized = value.strip().lower()
    if normalized in _YES_WORDS:
        summary = _claim_summary(state["data"])
        try:
            pdf_path = generate_claim_pdf(summary)
            summary["pdf_file_path"] = str(pdf_path)
        except Exception as exc:
            return ClaimTurnResult(
                message=(
                    "I could not generate the PDF right now. "
                    f"Error: {exc}"
                ),
                claim_summary=summary,
                citation=summary["coverage_source"],
            )

        _reset_state(state)
        return ClaimTurnResult(
            message=(
                "Your claim summary PDF is ready.\n"
                f"Saved to: {summary['pdf_file_path']}\n"
                "Attach your original receipt and submit it to your insurer."
            ),
            claim_summary=summary,
            citation=summary["coverage_source"],
        )

    if normalized in _NO_WORDS:
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
        "plan_id": data.get("plan_id", ""),
        "amount_limit_eur": data.get("amount_limit_eur"),
        "amount_limit_label": data.get("amount_limit_label", ""),
        "pdf_file_path": data.get("pdf_file_path", ""),
    }


def _extract_amount_limit_eur(coverage_details: str) -> float | None:
    multiplier_match = _MULTIPLIER_VALUE_PATTERN.search(coverage_details)
    if multiplier_match:
        amount = float(multiplier_match.group(1).replace(",", ""))
        visits = float(multiplier_match.group(2).replace(",", ""))
        return round(amount * visits, 2)

    single_cap_match = _SIMPLE_CAP_PATTERN.search(coverage_details)
    if single_cap_match:
        return round(float(single_cap_match.group(1).replace("EUR", "").replace("€", "").replace(",", "").strip()), 2)

    return None


def _extract_amount_limit_label(coverage_details: str) -> str:
    multiplier_match = _LIMIT_PATTERN.search(coverage_details)
    if multiplier_match:
        return _clean_limit_label(multiplier_match.group(1))

    single_cap_match = _SIMPLE_CAP_PATTERN.search(coverage_details)
    if single_cap_match:
        return _clean_limit_label(single_cap_match.group(1))

    return ""


def _format_limit_reference(limit_eur: float, limit_label: str) -> str:
    limit_amount = _format_chat_currency(limit_eur)
    normalized_label = limit_label.strip()
    if not normalized_label:
        return limit_amount
    if normalized_label == limit_amount:
        return limit_amount
    return f"{limit_amount} ({normalized_label})"


def _format_chat_currency(value: float) -> str:
    if float(value).is_integer():
        return f"€{value:,.0f}"
    return f"€{value:,.2f}"


def _clean_limit_label(value: str) -> str:
    normalized = " ".join(value.replace("EUR", "€").split())
    return normalized


def _reset_state(state) -> None:
    state.clear()
    state.update(initial_claim_state())

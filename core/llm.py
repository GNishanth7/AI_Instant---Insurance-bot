from __future__ import annotations

from dataclasses import dataclass, field

from config import ANSWER_DISCLAIMER, NOT_FOUND_MESSAGE
from core.retriever import RetrievalResult


@dataclass(slots=True)
class AssistantResponse:
    answer: str
    citation: str = ""
    sources: list[dict[str, str | float]] = field(default_factory=list)
    disclaimer: str = ANSWER_DISCLAIMER
    used_fallback: bool = False
    error: str = ""


@dataclass(slots=True)
class CoverageDecision:
    status: str
    summary: str
    citation: str = ""
    sources: list[dict[str, str | float]] = field(default_factory=list)
    used_fallback: bool = False
    error: str = ""


class PolicyAssistantLLM:
    def answer_question(
        self,
        question: str,
        retrieved_chunks: list[RetrievalResult],
        relevant_match: bool,
    ) -> AssistantResponse:
        sources = self._sources_from_results(retrieved_chunks)
        if not relevant_match:
            return AssistantResponse(
                answer=NOT_FOUND_MESSAGE,
                sources=sources,
                used_fallback=True,
            )

        top = retrieved_chunks[0]
        related = self._related_results(question, retrieved_chunks)
        if len(related) == 1:
            answer = f"{top.chunk.benefit}: {top.chunk.coverage}"
            citation = top.chunk.citation
        else:
            lines = [f"- {result.chunk.benefit}: {result.chunk.coverage}" for result in related]
            answer = "Relevant cover details:\n" + "\n".join(lines)
            citation = "; ".join(result.chunk.citation for result in related[:2])

        return AssistantResponse(
            answer=answer,
            citation=citation,
            sources=sources,
            used_fallback=True,
        )

    def check_treatment_coverage(
        self,
        treatment_type: str,
        retrieved_chunks: list[RetrievalResult],
        relevant_match: bool,
    ) -> CoverageDecision:
        sources = self._sources_from_results(retrieved_chunks)
        if not relevant_match or not retrieved_chunks:
            return CoverageDecision(
                status="unclear",
                summary=(
                    f"I could not confirm coverage for {treatment_type} in the selected policy data."
                ),
                sources=sources,
                used_fallback=True,
            )

        top = retrieved_chunks[0]
        coverage_text = top.chunk.coverage.lower()
        if any(token in coverage_text for token in ["not covered", "excluded", "not available"]):
            status = "no"
            summary = f"{top.chunk.benefit} is not covered. {top.chunk.coverage}"
        else:
            status = "yes"
            summary = f"{top.chunk.benefit} appears to be covered: {top.chunk.coverage}"

        return CoverageDecision(
            status=status,
            summary=summary,
            citation=top.chunk.citation,
            sources=sources,
            used_fallback=True,
        )

    @staticmethod
    def _related_results(
        question: str,
        retrieved_chunks: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        if not retrieved_chunks:
            return []

        top = retrieved_chunks[0]
        top_gap = max(top.score - 0.12, 0.25)
        related = [result for result in retrieved_chunks[:3] if result.score >= top_gap]

        lower_question = question.lower()
        if any(keyword in lower_question for keyword in ["dental", "maternity", "benefit", "cover"]):
            return related

        if top.match_ratio >= 0.8 or len(related) == 1:
            return [top]

        if top.score - related[-1].score > 0.18:
            return [top]

        return related

    @staticmethod
    def _sources_from_results(
        retrieved_chunks: list[RetrievalResult],
    ) -> list[dict[str, str | float]]:
        return [
            {
                "citation": result.chunk.citation,
                "benefit": result.chunk.benefit,
                "coverage": result.chunk.coverage,
                "score": round(result.score, 4),
            }
            for result in retrieved_chunks
        ]

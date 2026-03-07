from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from config import (
    ANSWER_DISCLAIMER,
    BENEFIT_SYNONYMS,
    ENABLE_GEMINI_ANSWER_GENERATION,
    GEMINI_API_KEY,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    NOT_FOUND_MESSAGE,
)
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
    def __init__(self) -> None:
        self._client: Any | None = None
        self._client_initialized = False

    @property
    def ai_generation_enabled(self) -> bool:
        return self._get_client() is not None

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

        related = self._related_results(question, retrieved_chunks)
        citation = "; ".join(result.chunk.citation for result in related[:2])
        generated_answer = self._generate_grounded_answer(question, related)
        if generated_answer:
            if generated_answer.strip() == NOT_FOUND_MESSAGE:
                return AssistantResponse(
                    answer=NOT_FOUND_MESSAGE,
                    sources=sources,
                    used_fallback=False,
                )
            return AssistantResponse(
                answer=generated_answer,
                citation=citation,
                sources=sources,
                used_fallback=False,
            )

        fallback_answer = self._fallback_answer(question, related)
        return AssistantResponse(
            answer=fallback_answer,
            citation=citation,
            sources=sources,
            used_fallback=True,
        )

    def answer_plan_overview(
        self,
        question: str,
        plan_name: str,
        overview_context: dict[str, Any],
    ) -> AssistantResponse:
        sources = self._overview_sources(overview_context)
        citation = "; ".join(
            str(source["citation"])
            for source in sources[:2]
            if source.get("citation")
        )
        generated_answer = self._generate_plan_overview_answer(
            question=question,
            plan_name=plan_name,
            overview_context=overview_context,
        )
        if generated_answer and generated_answer.strip() != NOT_FOUND_MESSAGE:
            return AssistantResponse(
                answer=generated_answer,
                citation=citation,
                sources=sources,
                used_fallback=False,
            )

        return AssistantResponse(
            answer=self._fallback_plan_overview(plan_name, overview_context),
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

    def _generate_grounded_answer(
        self,
        question: str,
        related_results: list[RetrievalResult],
    ) -> str:
        client = self._get_client()
        if client is None or not related_results:
            return ""

        context = self._context_block(related_results)
        prompt = (
            "You are a health insurance policy assistant.\n"
            "Use only the policy context provided below.\n"
            f"If the context does not clearly answer the question, reply exactly with: {NOT_FOUND_MESSAGE}\n"
            "Do not add outside knowledge.\n"
            "Keep all numbers, currencies, percentages, visit counts, limits, and excesses exactly as shown in the context.\n"
            "When multiple entries are relevant, synthesize them into one answer.\n"
            "Do not say something is excluded unless the context explicitly says it is excluded.\n"
            "When the retrieved entries only show a limited subset of cover, say that clearly using phrases like 'I only found ... in the provided policy context.'\n"
            "Do not include inline citations or source numbers in the answer.\n\n"
            "Start with a direct answer sentence.\n"
            "Then write 'Details:' followed by 2 to 4 bullet points.\n"
            "If the matches are narrow, add one bullet explaining that limitation.\n\n"
            f"Question:\n{question}\n\n"
            f"Policy context:\n{context}"
        )

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=self._generation_config(),
            )
        except Exception as exc:
            print(f"[gemini-generation-error] {exc!r}")
            return ""

        text = (getattr(response, "text", "") or "").strip()
        if text:
            return self._clean_generated_answer(text)

        return self._clean_generated_answer(self._extract_text_from_candidates(response).strip())

    def _generate_plan_overview_answer(
        self,
        question: str,
        plan_name: str,
        overview_context: dict[str, Any],
    ) -> str:
        client = self._get_client()
        if client is None:
            return ""

        context = self._plan_overview_context_block(plan_name, overview_context)
        prompt = (
            "You are a health insurance policy assistant helping a member understand their plan.\n"
            "Use only the plan overview context provided below.\n"
            f"If the context does not support the answer, reply exactly with: {NOT_FOUND_MESSAGE}\n"
            "Do not add outside knowledge.\n"
            "Keep all numbers, currencies, percentages, visit counts, limits, and excesses exactly as shown.\n"
            "Give a high-level explanation of the main areas of cover that appear in the selected plan.\n"
            "Do not claim a category is fully covered unless the context says so.\n"
            "You may mention these assistant capabilities exactly as product guidance: ask about a specific benefit, start a claim, or request an appointment.\n"
            "Do not include inline citations or source numbers in the answer.\n\n"
            "Write the answer in this structure:\n"
            "Overview: <2 to 3 sentences>\n"
            "Main areas of cover:\n"
            "- <category>: <short explanation using only the context>\n"
            "- <category>: <short explanation using only the context>\n"
            "How to make use of it:\n"
            "- <practical next step>\n"
            "- <practical next step>\n"
            "Good next questions:\n"
            "- <question>\n"
            "- <question>\n\n"
            f"Question:\n{question}\n\n"
            f"Plan overview context:\n{context}"
        )

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=self._generation_config(),
            )
        except Exception as exc:
            print(f"[gemini-overview-error] {exc!r}")
            return ""

        text = (getattr(response, "text", "") or "").strip()
        if text:
            return self._clean_generated_answer(text)

        return self._clean_generated_answer(self._extract_text_from_candidates(response).strip())

    def _get_client(self) -> Any | None:
        if self._client_initialized:
            return self._client

        self._client_initialized = True
        if not ENABLE_GEMINI_ANSWER_GENERATION or not GEMINI_API_KEY:
            self._client = None
            return None

        try:
            from google import genai
        except Exception:
            self._client = None
            return None

        try:
            self._client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception:
            self._client = None

        return self._client

    @staticmethod
    def _generation_config() -> Any:
        try:
            from google.genai import types

            return types.GenerateContentConfig(
                temperature=GEMINI_TEMPERATURE,
                max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
            )
        except Exception:
            return {
                "temperature": GEMINI_TEMPERATURE,
                "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
            }

    @staticmethod
    def _extract_text_from_candidates(response: Any) -> str:
        candidates = getattr(response, "candidates", None) or []
        parts: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            candidate_parts = getattr(content, "parts", None) or []
            for part in candidate_parts:
                text = getattr(part, "text", None)
                if text:
                    parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _clean_generated_answer(text: str) -> str:
        if not text:
            return ""

        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").replace("**", "")
        cleaned = re.sub(r"(?m)^\*\s+", "- ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _context_block(related_results: list[RetrievalResult]) -> str:
        blocks: list[str] = []
        for index, result in enumerate(related_results, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[Source {index}] {PolicyAssistantLLM._normalize_model_text(result.chunk.citation)}",
                        f"Category: {PolicyAssistantLLM._normalize_model_text(result.chunk.category)}",
                        f"Section: {PolicyAssistantLLM._normalize_model_text(result.chunk.section)}",
                        f"Benefit: {PolicyAssistantLLM._normalize_model_text(result.chunk.benefit)}",
                        f"Coverage: {PolicyAssistantLLM._normalize_model_text(result.chunk.coverage)}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _plan_overview_context_block(
        plan_name: str,
        overview_context: dict[str, Any],
    ) -> str:
        blocks = [
            f"Plan: {plan_name}",
            f"Benefit rows: {overview_context.get('benefit_count', 0)}",
            f"Categories: {overview_context.get('category_count', 0)}",
            f"Sections: {overview_context.get('section_count', 0)}",
        ]

        categories = overview_context.get("categories", []) or []
        for category in categories:
            sections = ", ".join(str(section) for section in category.get("sections", []))
            blocks.append(
                (
                    f"\nCategory: {PolicyAssistantLLM._normalize_model_text(str(category.get('category', '')))}\n"
                    f"Benefit count: {category.get('benefit_count', 0)}\n"
                    f"Sections: {PolicyAssistantLLM._normalize_model_text(sections)}"
                )
            )
            for example in category.get("examples", []):
                blocks.append(
                    (
                        f"- Example benefit: {PolicyAssistantLLM._normalize_model_text(str(example.get('benefit', '')))}\n"
                        f"  Coverage: {PolicyAssistantLLM._normalize_model_text(str(example.get('coverage', '')))}"
                    )
                )

        return "\n".join(blocks)

    def _fallback_answer(
        self,
        question: str,
        retrieved_chunks: list[RetrievalResult],
    ) -> str:
        if not retrieved_chunks:
            return NOT_FOUND_MESSAGE

        related = self._dedupe_results(self._related_results(question, retrieved_chunks))
        if not related:
            return NOT_FOUND_MESSAGE

        top = related[0]
        focus_label = self._focus_label(question, related)
        parts: list[str] = [self._fallback_intro(question, related, focus_label)]

        parts.append("")
        parts.append("Details:")
        for result in related[:4]:
            parts.append(
                f"- {self._location_label(result)}: "
                f"{result.chunk.benefit} - {result.chunk.coverage}"
            )

        notes = self._fallback_notes(question, related, focus_label)
        if notes:
            parts.append("")
            parts.append("What to note:")
            parts.extend(f"- {note}" for note in notes)

        if len(related) == 1 and top.chunk.citation:
            parts.append("")
            parts.append("This answer is based on one directly matched policy entry.")

        return "\n".join(parts)

    def _fallback_plan_overview(
        self,
        plan_name: str,
        overview_context: dict[str, Any],
    ) -> str:
        categories = overview_context.get("categories", []) or []
        benefit_count = int(overview_context.get("benefit_count", 0) or 0)
        category_count = int(overview_context.get("category_count", 0) or 0)
        section_count = int(overview_context.get("section_count", 0) or 0)

        parts = [
            (
                f"Here is a high-level overview of {plan_name}. "
                f"I found {benefit_count} benefit entries across {category_count} main areas "
                f"and {section_count} sections in the selected policy data."
            ),
            "",
            "Main areas of cover:",
        ]

        for category in categories[:5]:
            examples = category.get("examples", []) or []
            example_text = "; ".join(
                f"{example.get('benefit', 'Benefit')} ({example.get('coverage', 'Coverage not listed')})"
                for example in examples[:3]
            )
            category_name = str(category.get("category", "General"))
            category_benefits = category.get("benefit_count", 0)
            if example_text:
                parts.append(
                    f"- {category_name}: {category_benefits} benefit entries. "
                    f"Examples include {example_text}."
                )
            else:
                parts.append(f"- {category_name}: {category_benefits} benefit entries.")

        parts.extend(
            [
                "",
                "How to make use of it:",
                "- Ask about a specific benefit, treatment, or service such as MRI, physiotherapy, dental, maternity, GP visits, or prescriptions.",
                "- Use this assistant to check cover details, start a claim, or request an appointment for a treatment.",
                "- If you are not sure where to start, ask about one category such as outpatient, inpatient, hospital, or dental cover.",
                "",
                "Good next questions:",
                "- What outpatient cover do I have?",
                "- Does this plan cover physiotherapy?",
                "- What hospital cover do I have?",
            ]
        )
        return "\n".join(parts)

    @staticmethod
    def _related_results(
        question: str,
        retrieved_chunks: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        if not retrieved_chunks:
            return []

        top = retrieved_chunks[0]
        top_gap = max(top.score - 0.12, 0.25)
        candidate_pool = retrieved_chunks[:5]
        related = [result for result in candidate_pool if result.score >= top_gap]
        if not related:
            related = [top]

        lower_question = question.lower()
        if any(keyword in lower_question for keyword in ["dental", "maternity", "benefit", "cover"]):
            focus_terms = PolicyAssistantLLM._focus_terms(question)
            focused = [
                result
                for result in candidate_pool
                if PolicyAssistantLLM._chunk_matches_focus(result, focus_terms)
            ]
            if focused:
                return focused[:4]
            return related[:4]

        if top.match_ratio >= 0.8 or len(related) == 1:
            return [top]

        if top.score - related[-1].score > 0.18:
            return [top]

        return related[:3]

    @staticmethod
    def _dedupe_results(results: list[RetrievalResult]) -> list[RetrievalResult]:
        deduped: list[RetrievalResult] = []
        seen: set[tuple[str, str]] = set()

        for result in results:
            key = (
                result.chunk.benefit.strip().lower(),
                result.chunk.coverage.strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)

        return deduped

    @staticmethod
    def _location_label(result: RetrievalResult) -> str:
        category = result.chunk.category.strip()
        section = result.chunk.section.strip()
        if section and section != category:
            return f"{category} / {section}"
        return category or "Policy entry"

    @staticmethod
    def _focus_terms(question: str) -> set[str]:
        normalized_question = PolicyAssistantLLM._normalize_phrase(question)
        matches: set[str] = set()

        for canonical, aliases in BENEFIT_SYNONYMS.items():
            group = {canonical, *aliases}
            for term in group:
                normalized_term = PolicyAssistantLLM._normalize_phrase(term)
                if normalized_term and PolicyAssistantLLM._contains_normalized_term(
                    normalized_question,
                    normalized_term,
                ):
                    matches.add(canonical)
                    matches.update(group)
        return matches

    @staticmethod
    def _chunk_matches_focus(result: RetrievalResult, focus_terms: set[str]) -> bool:
        if not focus_terms:
            return False

        search_blob = PolicyAssistantLLM._normalize_phrase(
            " ".join(
                [
                    result.chunk.category,
                    result.chunk.section,
                    result.chunk.benefit,
                    result.chunk.coverage,
                ]
            )
        )
        return any(
            PolicyAssistantLLM._normalize_phrase(term) in search_blob for term in focus_terms
        )

    @staticmethod
    def _normalize_phrase(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @staticmethod
    def _normalize_for_model(value: str) -> str:
        return value.replace("€", "EUR ")

    @staticmethod
    def _contains_normalized_term(blob: str, term: str) -> bool:
        if not blob or not term:
            return False
        if " " in term:
            return term in blob
        return term in blob.split()

    @staticmethod
    def _normalize_model_text(value: str) -> str:
        return value.replace("â‚¬", "EUR ").replace("€", "EUR ")

    def _focus_label(
        self,
        question: str,
        results: list[RetrievalResult],
    ) -> str:
        for canonical in BENEFIT_SYNONYMS:
            if canonical in self._focus_terms(question):
                return canonical.replace("_", " ").title()

        if results:
            return results[0].chunk.benefit
        return "policy cover"

    @staticmethod
    def _coverage_status(coverage: str) -> str:
        lowered = coverage.lower()
        if any(token in lowered for token in ["not covered", "excluded", "not available"]):
            return "no"
        return "yes"

    def _fallback_intro(
        self,
        question: str,
        related: list[RetrievalResult],
        focus_label: str,
    ) -> str:
        statuses = {self._coverage_status(result.chunk.coverage) for result in related}
        label = focus_label.lower()

        if self._is_yes_no_question(question):
            if statuses == {"no"}:
                return (
                    f"No, based on the selected plan data, I did not find cover for {label} "
                    "in the matched entries."
                )
            return (
                f"Yes, based on the selected plan data, I found matching cover details for {label}."
            )

        if self._is_emergency_only(related):
            return (
                f"Based on the selected plan data, the {label} entries I found relate to "
                "emergency treatment only."
            )

        if len(related) == 1:
            return (
                f"Based on the selected plan data, I found one directly relevant entry for {label}."
            )

        return f"Based on the selected plan data, I found these {label} cover details."

    def _fallback_notes(
        self,
        question: str,
        related: list[RetrievalResult],
        focus_label: str,
    ) -> list[str]:
        notes: list[str] = []
        label = focus_label.lower()

        if self._is_emergency_only(related) and "emergency" not in self._normalize_phrase(question):
            notes.append(
                f"I only found emergency-related {label} entries in the retrieved policy matches."
            )

        section_notes = [
            result.chunk.section
            for result in related
            if result.chunk.section
            and result.chunk.section != result.chunk.category
            and any(token in result.chunk.section.lower() for token in ["excess", "co-payment"])
        ]
        if section_notes:
            unique_sections = []
            for section in section_notes:
                if section not in unique_sections:
                    unique_sections.append(section)
            notes.append(
                "One or more matching entries sit under sections that mention additional costs or "
                f"conditions, including: {', '.join(unique_sections)}."
            )

        monetary_limits = [
            result.chunk.coverage
            for result in related
            if any(token in result.chunk.coverage.lower() for token in ["up to", "per visit", "%", "eur"])
        ]
        if monetary_limits and len(related) > 1:
            notes.append(
                "Where limits are shown above, use those specific amounts or percentages rather than "
                "assuming full cover."
            )

        return notes

    @staticmethod
    def _is_emergency_only(related: list[RetrievalResult]) -> bool:
        if not related:
            return False

        return all(
            "emergency" in f"{result.chunk.benefit} {result.chunk.coverage}".lower()
            for result in related
        )

    @staticmethod
    def _is_yes_no_question(question: str) -> bool:
        lowered = question.strip().lower()
        return lowered.startswith(("does ", "do ", "is ", "are ", "can "))

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

    @staticmethod
    def _overview_sources(
        overview_context: dict[str, Any],
    ) -> list[dict[str, str | float]]:
        sources: list[dict[str, str | float]] = []
        for category in overview_context.get("categories", []) or []:
            for example in category.get("examples", []) or []:
                sources.append(
                    {
                        "citation": str(example.get("citation", "")),
                        "benefit": str(example.get("benefit", "")),
                        "coverage": str(example.get("coverage", "")),
                        "score": 1.0,
                    }
                )
                if len(sources) >= 6:
                    return sources
        return sources

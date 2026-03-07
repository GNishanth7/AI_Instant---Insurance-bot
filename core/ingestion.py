from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from config import BASE_DIR, BENEFIT_SYNONYMS, PLAN_FILE_GLOB

_MOJIBAKE_REPLACEMENTS = {
    "\u00e2\u201a\u00ac": "EUR",
    "\u00e2\u20ac\u2122": "'",
    "\u00e2\u20ac\u0153": '"',
    "\u00e2\u20ac\u009d": '"',
    "\u00e2\u20ac\u201c": "-",
}


@dataclass(slots=True)
class PolicyChunk:
    chunk_id: str
    plan_name: str
    source_file: str
    category: str
    section: str
    benefit: str
    coverage: str
    citation: str
    text: str

    def to_record(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, str]) -> "PolicyChunk":
        return cls(**record)


def discover_plan_files(root: Path | None = None) -> list[Path]:
    directory = root or BASE_DIR
    return sorted(directory.glob(PLAN_FILE_GLOB), key=_plan_sort_key)


def load_plan_chunks(plan_path: Path | str) -> list[PolicyChunk]:
    source_path = Path(plan_path)
    plan_name = source_path.stem
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    chunks: list[PolicyChunk] = []

    for category_index, category in enumerate(raw.get("TableOfCover", [])):
        category_name = normalize_text(category.get("Name", "General"))
        sections = category.get("Sections", [])
        for section_index, section in enumerate(sections):
            section_name = normalize_text(section.get("Name") or category_name)
            for subsection_index, subsection in enumerate(section.get("SubSections", [])):
                benefit = normalize_text(subsection.get("Benefit", "Unknown benefit"))
                coverage = normalize_text(subsection.get("Coverage", "Coverage not listed"))
                citation = build_citation(
                    source_file=source_path.name,
                    category=category_name,
                    section=section_name,
                    benefit=benefit,
                )
                chunk = PolicyChunk(
                    chunk_id=(
                        f"{plan_name}:{category_index}:{section_index}:{subsection_index}:"
                        f"{slugify(benefit)}"
                    ),
                    plan_name=plan_name,
                    source_file=source_path.name,
                    category=category_name,
                    section=section_name,
                    benefit=benefit,
                    coverage=coverage,
                    citation=citation,
                    text=build_chunk_text(
                        plan_name=plan_name,
                        category=category_name,
                        section=section_name,
                        benefit=benefit,
                        coverage=coverage,
                    ),
                )
                chunks.append(chunk)

    return chunks


def persist_chunk_records(chunks: list[PolicyChunk], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([chunk.to_record() for chunk in chunks], indent=2),
        encoding="utf-8",
    )


def load_persisted_chunk_records(input_path: Path) -> list[PolicyChunk]:
    records = json.loads(input_path.read_text(encoding="utf-8"))
    return [PolicyChunk.from_record(record) for record in records]


def build_citation(source_file: str, category: str, section: str, benefit: str) -> str:
    parts = [category]
    if section and section != category:
        parts.append(section)
    parts.append(benefit)
    return " > ".join(parts) + f" ({source_file})"


def build_chunk_text(
    plan_name: str,
    category: str,
    section: str,
    benefit: str,
    coverage: str,
) -> str:
    parts = [
        f"Plan: {plan_name}",
        f"Category: {category}",
        f"Section: {section}",
        f"Benefit: {benefit}",
        f"Coverage: {coverage}",
    ]
    aliases = resolve_related_terms(benefit)
    if aliases:
        parts.append(f"Related terms: {', '.join(aliases)}")
    return "\n".join(parts)


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""

    normalized = str(value)
    for broken, fixed in _MOJIBAKE_REPLACEMENTS.items():
        normalized = normalized.replace(broken, fixed)

    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line)


def resolve_related_terms(benefit: str) -> list[str]:
    benefit_lower = benefit.lower()
    related: list[str] = []

    for canonical, aliases in BENEFIT_SYNONYMS.items():
        terms = [canonical, *aliases]
        if any(_contains_phrase(benefit_lower, term) for term in terms):
            related.extend(terms)

    deduped: list[str] = []
    for term in related:
        if term not in deduped:
            deduped.append(term)
    return deduped


def summarize_plan(chunks: list[PolicyChunk]) -> dict[str, int]:
    categories = {chunk.category for chunk in chunks}
    sections = {chunk.section for chunk in chunks}
    return {
        "benefit_count": len(chunks),
        "category_count": len(categories),
        "section_count": len(sections),
    }


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _plan_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"(\d+)$", path.stem)
    order = int(match.group(1)) if match else 9999
    return order, path.name.lower()


def _contains_phrase(blob: str, phrase: str) -> bool:
    blob_tokens = set(re.findall(r"[a-z0-9]+", blob.lower()))
    phrase_tokens = re.findall(r"[a-z0-9]+", phrase.lower())
    if not phrase_tokens:
        return False
    if len(phrase_tokens) == 1:
        return phrase_tokens[0] in blob_tokens
    normalized_blob = re.sub(r"[^a-z0-9]+", " ", blob.lower()).strip()
    normalized_phrase = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
    return normalized_phrase in normalized_blob

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import (
    BENEFIT_SYNONYMS,
    EMBEDDING_MODEL,
    FAISS_INDEX_DIR,
    INDEX_VERSION,
    KEYWORD_SCORE_WEIGHT,
    MIN_COMBINED_SCORE,
    MIN_KEYWORD_SCORE,
    MIN_VECTOR_SCORE,
    STOPWORDS,
    TOP_K_RETRIEVAL,
)
from core.ingestion import (
    PolicyChunk,
    load_persisted_chunk_records,
    load_plan_chunks,
    normalize_text,
    persist_chunk_records,
)


@dataclass(slots=True)
class RetrievalResult:
    chunk: PolicyChunk
    score: float
    vector_score: float
    keyword_score: float
    match_ratio: float
    matched_terms: list[str]


class PlanRetriever:
    _embedding_model_cache: dict[str, Any] = {}

    def __init__(self, plan_path: Path | str):
        self.plan_path = Path(plan_path)
        self.plan_name = self.plan_path.stem
        self.plan_index_dir = FAISS_INDEX_DIR / self.plan_name
        self.index_path = self.plan_index_dir / "index.faiss"
        self.chunk_path = self.plan_index_dir / "chunks.json"
        self.manifest_path = self.plan_index_dir / "manifest.json"
        self.chunks: list[PolicyChunk] = []
        self._vector_index: Any | None = None
        self._vector_enabled = False

    @property
    def vector_enabled(self) -> bool:
        return self._vector_enabled

    def ensure_index(self, force_rebuild: bool = False) -> None:
        if force_rebuild or not self._has_fresh_index():
            self._build_index()
            return
        self._load_index()

    def rebuild(self) -> None:
        self.ensure_index(force_rebuild=True)

    def plan_stats(self) -> dict[str, Any]:
        self.ensure_index()
        return {
            "plan_name": self.plan_name,
            "chunk_count": len(self.chunks),
            "vector_enabled": self.vector_enabled,
        }

    def retrieve(self, query: str, top_k: int = TOP_K_RETRIEVAL) -> list[RetrievalResult]:
        self.ensure_index()
        if not self.chunks:
            return []

        vector_scores = self._search_vectors(query) if self.vector_enabled else {}
        results: list[RetrievalResult] = []

        for chunk in self.chunks:
            keyword_score, matched_terms, match_ratio = self._keyword_score(query, chunk)
            vector_score = vector_scores.get(chunk.chunk_id, 0.0)
            score = (
                vector_score + (keyword_score * KEYWORD_SCORE_WEIGHT)
                if self.vector_enabled
                else keyword_score
            )
            if score <= 0:
                continue

            results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=score,
                    vector_score=vector_score,
                    keyword_score=keyword_score,
                    match_ratio=match_ratio,
                    matched_terms=matched_terms,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def has_relevant_match(self, results: list[RetrievalResult]) -> bool:
        if not results:
            return False

        top = results[0]
        if top.score < MIN_COMBINED_SCORE:
            return False
        if top.match_ratio < 0.5 and top.keyword_score < 0.75 and top.vector_score < 0.45:
            return False
        if top.keyword_score < MIN_KEYWORD_SCORE and top.vector_score < MIN_VECTOR_SCORE:
            return False
        if not top.matched_terms and top.keyword_score < MIN_KEYWORD_SCORE:
            return False
        return True

    def _has_fresh_index(self) -> bool:
        if not self.manifest_path.exists() or not self.chunk_path.exists():
            return False

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("index_version") != INDEX_VERSION:
            return False
        if manifest.get("source_mtime") != self.plan_path.stat().st_mtime:
            return False
        if manifest.get("embedding_model") != EMBEDDING_MODEL:
            return False
        if manifest.get("vector_enabled") and not self.index_path.exists():
            return False
        return True

    def _build_index(self) -> None:
        self.plan_index_dir.mkdir(parents=True, exist_ok=True)
        self.chunks = load_plan_chunks(self.plan_path)
        persist_chunk_records(self.chunks, self.chunk_path)

        self._vector_index = None
        self._vector_enabled = False
        try:
            vectors, faiss = self._encode_texts([chunk.text for chunk in self.chunks])
            index = faiss.IndexFlatIP(vectors.shape[1])
            index.add(vectors)
            faiss.write_index(index, str(self.index_path))
            self._vector_index = index
            self._vector_enabled = True
        except Exception:
            self._vector_index = None
            self._vector_enabled = False

        manifest = {
            "index_version": INDEX_VERSION,
            "source_file": self.plan_path.name,
            "source_mtime": self.plan_path.stat().st_mtime,
            "embedding_model": EMBEDDING_MODEL,
            "vector_enabled": self._vector_enabled,
            "chunk_count": len(self.chunks),
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _load_index(self) -> None:
        self.chunks = load_persisted_chunk_records(self.chunk_path)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._vector_enabled = bool(manifest.get("vector_enabled"))
        if not self._vector_enabled:
            self._vector_index = None
            return

        faiss = importlib.import_module("faiss")
        self._vector_index = faiss.read_index(str(self.index_path))

    def _encode_texts(self, texts: list[str]) -> tuple[Any, Any]:
        model = self._get_embedding_model()
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return vectors.astype("float32"), importlib.import_module("faiss")

    def _get_embedding_model(self) -> Any:
        if EMBEDDING_MODEL in self._embedding_model_cache:
            return self._embedding_model_cache[EMBEDDING_MODEL]

        sentence_transformers = importlib.import_module("sentence_transformers")
        model = sentence_transformers.SentenceTransformer(EMBEDDING_MODEL)
        self._embedding_model_cache[EMBEDDING_MODEL] = model
        return model

    def _search_vectors(self, query: str) -> dict[str, float]:
        if not self._vector_index:
            return {}

        query_embedding, _ = self._encode_texts([self._expanded_query_text(query)])
        scores, indices = self._vector_index.search(query_embedding, len(self.chunks))
        vector_scores: dict[str, float] = {}

        for score, index in zip(scores[0], indices[0]):
            if index < 0:
                continue
            vector_scores[self.chunks[index].chunk_id] = float(score)

        return vector_scores

    def _keyword_score(self, query: str, chunk: PolicyChunk) -> tuple[float, list[str], float]:
        query_terms = self._expanded_terms(query)
        if not query_terms:
            return 0.0, [], 0.0

        search_blob = normalize_text(
            " ".join(
                [
                    chunk.category,
                    chunk.section,
                    chunk.benefit,
                    chunk.coverage,
                    chunk.text,
                ]
            )
        ).lower()
        chunk_tokens = self._tokenize(search_blob)
        matched_terms = sorted(
            term
            for term in query_terms
            if self._term_matches_blob(term, search_blob, chunk_tokens)
        )

        if not matched_terms:
            return 0.0, [], 0.0

        overlap_score = len(matched_terms) / len(query_terms)
        benefit_text = chunk.benefit.lower()
        phrase_bonus = 0.0
        for term in matched_terms:
            if term in benefit_text:
                phrase_bonus += 0.18
            elif term in search_blob:
                phrase_bonus += 0.08

        normalized_query = self._normalize_phrase(query)
        if normalized_query and normalized_query in self._normalize_phrase(chunk.benefit):
            phrase_bonus += 0.50

        return min(1.0, overlap_score + phrase_bonus), matched_terms, overlap_score

    def _expanded_terms(self, query: str) -> set[str]:
        normalized_query = normalize_text(query).lower()
        terms = self._tokenize(normalized_query)
        phrases: set[str] = set()

        for canonical, aliases in BENEFIT_SYNONYMS.items():
            group = {canonical, *aliases}
            if any(self._contains_phrase(normalized_query, term) for term in group):
                phrases.update(group)
                for phrase in group:
                    terms.update(self._tokenize(phrase))

        for phrase in phrases:
            if " " in phrase and len(phrase) > 2:
                terms.add(phrase)

        return {term for term in terms if term and term not in STOPWORDS}

    def _expanded_query_text(self, query: str) -> str:
        terms = sorted(self._expanded_terms(query))
        return query if not terms else query + "\nRelated terms: " + ", ".join(terms)

    @staticmethod
    def _normalize_phrase(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.lower())
            if token and token not in STOPWORDS
        }

    @classmethod
    def _contains_phrase(cls, blob: str, phrase: str) -> bool:
        normalized_blob = cls._normalize_phrase(blob)
        normalized_phrase = cls._normalize_phrase(phrase)
        if not normalized_phrase:
            return False
        if " " in normalized_phrase:
            return normalized_phrase in normalized_blob
        return normalized_phrase in cls._tokenize(normalized_blob)

    @classmethod
    def _term_matches_blob(cls, term: str, search_blob: str, chunk_tokens: set[str]) -> bool:
        normalized_term = cls._normalize_phrase(term)
        if not normalized_term:
            return False
        if " " in normalized_term:
            return cls._contains_phrase(search_blob, normalized_term)
        return normalized_term in chunk_tokens

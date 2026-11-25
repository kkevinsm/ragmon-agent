from collections import Counter
import math
import os
from pathlib import Path
import re

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

load_dotenv()

EMBEDDING_DIM = 384
DEFAULT_COLLECTION = "documents"
_TOKEN_RE = re.compile(r"[a-z0-9_./-]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _compute_bm25_scores(query_text: str, docs: list[str]) -> list[float]:
    """Menghitung skor BM25 ternormalisasi [0, 1] untuk mencocokkan kata kunci persis."""
    if not query_text.strip() or not docs:
        return [0.0] * len(docs)

    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return [0.0] * len(docs)

    tokenized_docs = [_tokenize(doc) for doc in docs]
    doc_freqs: Counter[str] = Counter()
    for tokens in tokenized_docs:
        doc_freqs.update(set(tokens))

    n_docs = len(tokenized_docs)
    avgdl = sum(len(t) for t in tokenized_docs) / max(n_docs, 1)
    k1, b = 1.5, 0.75

    raw_scores: list[float] = []
    q_lower = query_text.strip().lower()
    for idx, tokens in enumerate(tokenized_docs):
        if not tokens:
            raw_scores.append(0.0)
            continue
        tf_counts = Counter(tokens)
        dl = len(tokens)
        score = 0.0
        for qt in query_tokens:
            df = doc_freqs.get(qt, 0)
            if df == 0:
                continue
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            tf = tf_counts.get(qt, 0)
            denom = tf + k1 * (1.0 - b + b * (dl / max(avgdl, 1.0)))
            score += idf * ((tf * (k1 + 1.0)) / max(denom, 1e-9))

        # Bonus kecil jika frasa atau istilah teknis muncul persis
        if len(q_lower) >= 4 and q_lower in docs[idx].lower():
            score *= 1.25
        raw_scores.append(score)

    max_score = max(raw_scores) if raw_scores else 0.0
    if max_score <= 0.0:
        return [0.0] * len(docs)
    return [s / max_score for s in raw_scores]


class QdrantStorage:
    """Wrapper untuk operasi Qdrant vector database (hybrid search, upsert, delete, list)."""

    def __init__(
        self,
        url: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        dim: int = EMBEDDING_DIM,
    ) -> None:
        resolved_url = (url if url is not None else os.getenv("QDRANT_URL", "http://localhost:6333")).strip()
        if not resolved_url or resolved_url.lower() == "local":
            local_path = Path(__file__).resolve().parent / "qdrant_storage"
            self.client = QdrantClient(path=str(local_path))
        else:
            self.client = QdrantClient(url=resolved_url, timeout=30)

        self.collection = collection
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None:
        points = [
            PointStruct(id=ids[i], vector=vectors[i], payload=payloads[i])
            for i in range(len(ids))
        ]
        self.client.upsert(collection_name=self.collection, points=points)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        source_filters: list[str] | None = None,
        query_text: str = "",
    ) -> dict:
        query_filter = None
        cleaned_filters = [s for s in (source_filters or []) if s]
        if cleaned_filters:
            query_filter = Filter(
                must=[FieldCondition(key="source", match=MatchAny(any=cleaned_filters))]
            )

        candidate_limit = max(top_k * 4, 20)
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            with_payload=True,
            limit=candidate_limit,
        )

        candidates: list[dict] = []
        for point in response.points:
            payload = point.payload or {}
            child_text = payload.get("text", "")
            parent_text = payload.get("parent_text") or child_text
            source = payload.get("source", "")
            page_label = str(payload.get("page_label", "") or "")
            if child_text:
                semantic_score = max(0.0, min(1.0, float(point.score or 0.0)))
                candidates.append(
                    {
                        "source": source,
                        "match_text": child_text,
                        "text": parent_text,
                        "page_label": page_label,
                        "semantic_score": semantic_score,
                    }
                )

        bm25_scores = _compute_bm25_scores(query_text, [c["match_text"] for c in candidates])
        has_kw = any(s > 0.0 for s in bm25_scores)

        for idx, cand in enumerate(candidates):
            kw = bm25_scores[idx]
            sem = cand["semantic_score"]
            hybrid = (0.70 * sem + 0.30 * kw) if has_kw else sem
            cand["keyword_score"] = round(kw, 4)
            cand["semantic_score"] = round(sem, 4)
            cand["score"] = round(hybrid, 4)

        candidates.sort(key=lambda item: item["score"], reverse=True)

        top_items: list[dict] = []
        seen_parents: set[tuple[str, str]] = set()
        for item in candidates:
            key = (item["source"], item["text"])
            if key in seen_parents:
                continue
            seen_parents.add(key)
            top_items.append(
                {
                    "source": item["source"],
                    "text": item["text"],
                    "page_label": item["page_label"],
                    "score": item["score"],
                    "semantic_score": item["semantic_score"],
                    "keyword_score": item["keyword_score"],
                }
            )
            if len(top_items) >= top_k:
                break

        contexts = [item["text"] for item in top_items]
        sources = sorted({item["source"] for item in top_items if item["source"]})
        return {"contexts": contexts, "sources": sources, "evidences": top_items}

    def delete_by_source(self, source_id: str) -> None:
        """Menghapus seluruh vektor milik dokumen tertentu berdasarkan payload source."""
        self.client.delete(
            collection_name=self.collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value=source_id))]
                )
            ),
        )

    def list_sources(self) -> list[str]:
        """Mengembalikan daftar unik nama dokumen (source) yang sudah terindeks di Qdrant."""
        return [item["source"] for item in self.get_source_stats()]

    def get_source_stats(self) -> list[dict]:
        """Mengembalikan statistik jumlah chunks per dokumen terindeks."""
        counts: Counter[str] = Counter()
        next_offset = None

        while True:
            records, next_offset = self.client.scroll(
                collection_name=self.collection,
                limit=100,
                offset=next_offset,
                with_payload=["source"],
                with_vectors=False,
            )
            for record in records:
                payload = record.payload or {}
                src = payload.get("source")
                if src:
                    counts[str(src)] += 1
            if next_offset is None:
                break

        return [{"source": src, "chunks": counts[src]} for src in sorted(counts)]

    def preview_source(self, source_id: str, limit: int = 3) -> list[dict[str, str]]:
        """Mengambil cuplikan awal isi dokumen dari Qdrant untuk fitur preview."""
        records, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source_id))]
            ),
            limit=max(limit * 3, 6),
            with_payload=True,
            with_vectors=False,
        )
        excerpts: list[dict[str, str]] = []
        seen: set[str] = set()
        for record in records:
            payload = record.payload or {}
            text = str(payload.get("parent_text") or payload.get("text") or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            excerpts.append(
                {
                    "page_label": str(payload.get("page_label", "") or ""),
                    "text": text,
                }
            )
            if len(excerpts) >= limit:
                break
        return excerpts

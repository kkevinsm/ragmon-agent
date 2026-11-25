from pydantic import BaseModel


class RAGChunkAndSrc(BaseModel):
    """Payload hasil pembacaan dan chunking dokumen."""

    chunks: list[str]
    parent_texts: list[str] = []
    page_labels: list[str] = []
    source_id: str | None = None
    used_ocr: bool = False


class RAGUpsertResult(BaseModel):
    """Hasil penyimpanan vektor ke Qdrant."""

    ingested: int
    used_ocr: bool = False


class RAGEvidence(BaseModel):
    """Potongan bukti kutipan dokumen beserta skor kemiripan."""

    source: str
    text: str
    page_label: str = ""
    score: float
    semantic_score: float = 0.0
    keyword_score: float = 0.0


class RAGSearchResult(BaseModel):
    """Hasil pencarian konteks relevan dari Qdrant."""

    contexts: list[str]
    sources: list[str]
    evidences: list[RAGEvidence] = []


class RAGQueryResult(BaseModel):
    """Hasil akhir jawaban RAG beserta sitasi, bukti kutipan, dan info model."""

    answer: str
    sources: list[str]
    num_contexts: int
    evidences: list[RAGEvidence] = []
    provider: str = ""
    model: str = ""

import datetime
import logging
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
import inngest
import inngest.fast_api

from ai_engine import generate_with_ai
from custom_types import (
    RAGChunkAndSrc,
    RAGEvidence,
    RAGQueryResult,
    RAGSearchResult,
    RAGUpsertResult,
)
from data_loader import embed_text, load_and_chunk_with_status
from vector_db import QdrantStorage

load_dotenv()

logger = logging.getLogger("uvicorn")

inngest_client = inngest.Inngest(
    app_id="ragmon",
    logger=logger,
    is_production=False,
    serializer=inngest.PydanticSerializer(),
)

SYSTEM_INSTRUCTION = (
    "Kamu adalah Mon-chan, asisten AI berpersona Anime Girl yang ceria, ramah, dan suportif. "
    "Kamu boleh menggunakan sapaan ringan seperti 'Senpai~' dan gaya bicara yang ekspresif, "
    "tetapi jawabanmu HARUS tetap jelas, terstruktur, dan akurat tanpa karakter em dash.\n\n"
    "ATURAN KETAT:\n"
    "1. Jawab pertanyaan HANYA berdasarkan 'Konteks Dokumen' yang diberikan.\n"
    "2. JANGAN mengarang fakta di luar konteks. Jika jawabannya tidak ada di konteks, "
    "katakan dengan jujur dan imut bahwa informasi tersebut tidak ditemukan di dokumen.\n"
    "3. Jawab dalam bahasa yang sama dengan pertanyaan pengguna."
)


@inngest_client.create_function(
    fn_id="RAGMON: Ingest PDF",
    trigger=inngest.TriggerEvent(event="rag/ingest_pdf"),
    throttle=inngest.Throttle(limit=2, period=datetime.timedelta(minutes=1)),
    rate_limit=inngest.RateLimit(
        limit=1,
        period=datetime.timedelta(hours=4),
        key="event.data.source_id",
    ),
    concurrency=[inngest.Concurrency(limit=2)],
)
async def rag_ingest_pdf(ctx: inngest.Context) -> dict:
    def _load(pdf_path: str, source_id: str, enable_ocr: bool) -> RAGChunkAndSrc:
        items, used_ocr = load_and_chunk_with_status(pdf_path, enable_ocr=enable_ocr)
        return RAGChunkAndSrc(
            chunks=[it["text"] for it in items],
            parent_texts=[it.get("parent_text", it["text"]) for it in items],
            page_labels=[it["page_label"] for it in items],
            source_id=source_id,
            used_ocr=used_ocr,
        )

    def _upsert(
        chunks: list[str],
        parent_texts: list[str],
        page_labels: list[str],
        source_id: str,
        used_ocr: bool,
    ) -> RAGUpsertResult:
        if not chunks:
            return RAGUpsertResult(ingested=0, used_ocr=used_ocr)
        vecs = embed_text(chunks)
        ids = [
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}:{i}"))
            for i in range(len(chunks))
        ]
        payloads = [
            {
                "source": source_id,
                "text": chunks[i],
                "parent_text": parent_texts[i] if i < len(parent_texts) else chunks[i],
                "page_label": page_labels[i] if i < len(page_labels) else "",
            }
            for i in range(len(chunks))
        ]
        QdrantStorage().upsert(ids=ids, vectors=vecs, payloads=payloads)
        return RAGUpsertResult(ingested=len(chunks), used_ocr=used_ocr)

    pdf_path = str(ctx.event.data["pdf_path"])
    source_id = str(ctx.event.data.get("source_id") or os.path.basename(pdf_path))
    enable_ocr = bool(ctx.event.data.get("enable_ocr", False))

    chunk_data = await ctx.step.run(
        "load-and-chunk",
        lambda: _load(pdf_path, source_id, enable_ocr),
        output_type=RAGChunkAndSrc,
    )
    upsert_res = await ctx.step.run(
        "embed-and-upsert",
        lambda: _upsert(
            chunk_data.chunks,
            chunk_data.parent_texts,
            chunk_data.page_labels,
            chunk_data.source_id or source_id,
            chunk_data.used_ocr,
        ),
        output_type=RAGUpsertResult,
    )
    return upsert_res.model_dump()


@inngest_client.create_function(
    fn_id="RAGMON: Query PDF AI",
    trigger=inngest.TriggerEvent(event="rag/query_pdf_ai"),
    throttle=inngest.Throttle(limit=10, period=datetime.timedelta(minutes=1)),
    concurrency=[inngest.Concurrency(limit=3)],
)
async def rag_query_pdf_ai(ctx: inngest.Context) -> dict:
    def _search(question: str, top_k: int, source_filters: list[str]) -> RAGSearchResult:
        query_vec = embed_text([question])[0]
        found = QdrantStorage().search(
            query_vector=query_vec,
            top_k=top_k,
            source_filters=source_filters,
            query_text=question,
        )
        evidences = [RAGEvidence(**item) for item in found.get("evidences", [])]
        return RAGSearchResult(
            contexts=found["contexts"],
            sources=found["sources"],
            evidences=evidences,
        )

    def _generate(
        question: str,
        contexts: list[str],
        chat_history: list[dict],
        custom_api_key: str | None,
        provider: str | None,
    ) -> dict[str, str]:
        if not contexts:
            return {
                "answer": (
                    "Maaf ya Senpai, aku sudah cari di seluruh catatan dokumen, "
                    "tetapi belum ada informasi yang cocok. Coba unggah dokumen dulu atau tanyakan topik lain ya."
                ),
                "provider": "none",
                "model": "none",
            }

        context_block = "\n\n".join(f"- {c}" for c in contexts)
        history_lines = []
        for msg in chat_history[-6:]:
            role = "User" if msg.get("role") == "user" else "Mon-chan"
            history_lines.append(f"{role}: {msg.get('content', '')}")
        history_block = "\n".join(history_lines) if history_lines else "(Belum ada riwayat)"

        user_prompt = (
            f"Riwayat Chat Terakhir:\n{history_block}\n\n"
            f"Konteks Dokumen:\n{context_block}\n\n"
            f"Pertanyaan Pengguna: {question}\n\n"
            "Jawaban Mon-chan:"
        )
        text, used_provider, used_model = generate_with_ai(
            system_instruction=SYSTEM_INSTRUCTION,
            user_prompt=user_prompt,
            api_key=custom_api_key,
            provider=provider,
        )
        return {"answer": text, "provider": used_provider, "model": used_model}

    question = str(ctx.event.data["question"])
    top_k = int(ctx.event.data.get("top_k", 5))
    chat_history = ctx.event.data.get("chat_history") or []
    source_filters = [str(s) for s in (ctx.event.data.get("source_filters") or [])]
    custom_api_key = ctx.event.data.get("custom_api_key")
    provider = ctx.event.data.get("provider")

    search_res = await ctx.step.run(
        "embed-and-search",
        lambda: _search(question, top_k, source_filters),
        output_type=RAGSearchResult,
    )

    gen_res = await ctx.step.run(
        "generate-answer",
        lambda: _generate(question, search_res.contexts, chat_history, custom_api_key, provider),
    )

    result = RAGQueryResult(
        answer=gen_res["answer"],
        sources=search_res.sources,
        num_contexts=len(search_res.contexts),
        evidences=search_res.evidences,
        provider=gen_res.get("provider", ""),
        model=gen_res.get("model", ""),
    )
    return result.model_dump()


app = FastAPI(title="RAGMON API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sources")
def list_sources() -> dict[str, list[str]]:
    return {"sources": QdrantStorage().list_sources()}


@app.get("/sources/stats")
def source_stats() -> dict[str, list[dict]]:
    return {"stats": QdrantStorage().get_source_stats()}


@app.get("/sources/{source_id}/preview")
def preview_source(source_id: str, limit: int = 3) -> dict:
    return {"source": source_id, "excerpts": QdrantStorage().preview_source(source_id, limit=limit)}


@app.delete("/sources/{source_id}")
def delete_source(source_id: str) -> dict[str, str]:
    QdrantStorage().delete_by_source(source_id)
    return {"deleted": source_id}


inngest.fast_api.serve(app, inngest_client, [rag_ingest_pdf, rag_query_pdf_ai])

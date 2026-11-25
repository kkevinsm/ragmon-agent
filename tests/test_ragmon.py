from pathlib import Path
import uuid

from docx import Document
from fastapi.testclient import TestClient
import pytest

import ai_engine
import data_loader
from data_loader import EMBED_MODEL_NAME, embed_text, load_and_chunk_file, load_and_chunk_with_status
import main
from streamlit_app import _export_chat_markdown, _poll_run_output
from vector_db import QdrantStorage


def test_load_and_chunk_file_multiformat(tmp_path: Path) -> None:
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("RAGMON membaca file teks biasa.", encoding="utf-8")

    md_file = tmp_path / "sample.md"
    md_file.write_text("# Judul\nKonten markdown untuk diindeks.", encoding="utf-8")

    docx_file = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("Paragraf Word untuk RAGMON.")
    doc.save(str(docx_file))

    assert len(load_and_chunk_file(str(txt_file))) == 1
    assert len(load_and_chunk_file(str(md_file))) == 1
    assert len(load_and_chunk_file(str(docx_file))) == 1


def test_load_and_chunk_unsupported_extension(tmp_path: Path) -> None:
    bad_file = tmp_path / "data.csv"
    bad_file.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Format file tidak didukung"):
        load_and_chunk_file(str(bad_file))


def test_embed_text_shape_and_empty() -> None:
    assert embed_text([]) == []
    vectors = embed_text(["halo dunia"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 384
    assert EMBED_MODEL_NAME == "BAAI/bge-small-en-v1.5"


def test_qdrant_hybrid_filter_and_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "")
    # Gunakan path sementara agar test tidak menyentuh data Qdrant utama
    from qdrant_client import QdrantClient

    storage = QdrantStorage.__new__(QdrantStorage)
    storage.client = QdrantClient(path=str(tmp_path / "qdrant"))
    storage.collection = "documents_pytest"
    from qdrant_client.models import Distance, VectorParams

    storage.client.create_collection(
        collection_name=storage.collection,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )

    docs = [
        "Ringkasan arsitektur sistem dan deployment.",
        "Kode error ERR_QDRANT_503 terjadi ketika upsert timeout.",
    ]
    vecs = embed_text(docs)
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    storage.upsert(
        ids=ids,
        vectors=vecs,
        payloads=[
            {"source": "arch.md", "text": docs[0], "parent_text": docs[0], "page_label": ""},
            {"source": "errors.txt", "text": docs[1], "parent_text": "PARENT: " + docs[1], "page_label": "2"},
        ],
    )

    assert storage.list_sources() == ["arch.md", "errors.txt"]
    assert storage.get_source_stats() == [
        {"source": "arch.md", "chunks": 1},
        {"source": "errors.txt", "chunks": 1},
    ]
    previews = storage.preview_source("errors.txt", limit=2)
    assert len(previews) == 1
    assert previews[0]["text"].startswith("PARENT:")

    q_vec = embed_text(["ERR_QDRANT_503"])[0]
    hybrid_res = storage.search(q_vec, top_k=2, query_text="ERR_QDRANT_503")
    assert hybrid_res["evidences"][0]["source"] == "errors.txt"
    assert hybrid_res["evidences"][0]["text"].startswith("PARENT:")
    assert hybrid_res["evidences"][0]["page_label"] == "2"
    assert hybrid_res["evidences"][0]["keyword_score"] > 0

    filtered_res = storage.search(q_vec, top_k=2, source_filters=["arch.md"])
    assert filtered_res["sources"] == ["arch.md"]

    storage.delete_by_source("arch.md")
    assert storage.list_sources() == ["errors.txt"]


def test_fastapi_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStorage:
        deleted: list[str] = []

        def list_sources(self) -> list[str]:
            return ["guide.pdf", "notes.md"]

        def delete_by_source(self, source_id: str) -> None:
            self.deleted.append(source_id)

    fake = FakeStorage()
    monkeypatch.setattr(main, "QdrantStorage", lambda: fake)

    client = TestClient(main.app)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/sources").json() == {"sources": ["guide.pdf", "notes.md"]}
    res = client.delete("/sources/guide.pdf")
    assert res.status_code == 200
    assert res.json() == {"deleted": "guide.pdf"}
    assert fake.deleted == ["guide.pdf"]


def test_export_chat_markdown() -> None:
    md = _export_chat_markdown([
        {"role": "user", "content": "Apa poin utamanya?", "sources": []},
        {
            "role": "assistant",
            "content": "Poin utamanya adalah orkestrasi Inngest.",
            "sources": ["guide.pdf"],
            "evidences": [{"source": "guide.pdf", "page_label": "3", "score": 0.91, "text": "Inngest menangani retry."}],
        },
    ])
    assert "# RAGMON Chat Export" in md
    assert "## User" in md
    assert "## Mon-chan" in md
    assert "`guide.pdf` (Hal. 3)" in md
    assert "91.0%" in md


def test_detect_provider_prefixes() -> None:
    assert ai_engine.detect_provider("sk-ant-abc") == "anthropic"
    assert ai_engine.detect_provider("xai-abc") == "xai"
    assert ai_engine.detect_provider("sk-proj-abc") == "openai"
    assert ai_engine.detect_provider("AIzaSy123") == "gemini"
    assert ai_engine.detect_provider("sk-abc", explicit_provider="xai") == "xai"


def test_generate_with_ai_failover_and_401(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResp:
        def __init__(self, status_code: int, body: dict | None = None, text: str = "") -> None:
            self.status_code = status_code
            self._body = body or {}
            self.text = text
            self.ok = 200 <= status_code < 300

        def json(self) -> dict:
            return self._body

    calls: list[str] = []

    def fake_openai(url, api_key, model, system_instruction, user_prompt, timeout_s):
        calls.append(model)
        if model == "gpt-4o-mini":
            return FakeResp(429, text="rate limit")
        return FakeResp(200, body={"choices": [{"message": {"content": "Halo Senpai!"}}]})

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_openai)
    text, prov, mod = ai_engine.generate_with_ai("sys", "user", api_key="sk-test")
    assert text == "Halo Senpai!"
    assert prov == "openai"
    assert mod == "gpt-4.1-mini"
    assert calls == ["gpt-4o-mini", "gpt-4.1-mini"]

    def fake_401(*args, **kwargs):
        return FakeResp(401, text="invalid key")

    monkeypatch.setattr(ai_engine, "_call_openai_compatible", fake_401)
    with pytest.raises(RuntimeError, match="tidak valid"):
        ai_engine.generate_with_ai("sys", "user", api_key="sk-bad")


def test_poll_run_output_waits_for_ended_at(monkeypatch: pytest.MonkeyPatch) -> None:
    import streamlit_app

    responses = iter([
        {"data": [{"status": "Completed", "ended_at": None}]},
        {"data": [{"status": "Completed", "ended_at": "2026-11-25T09:49:56Z", "output": {"answer": "OK"}}]},
    ])

    class FakeResp:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._payload

    monkeypatch.setattr(streamlit_app.requests, "get", lambda *a, **kw: FakeResp(next(responses)))
    out = _poll_run_output("evt-1", timeout_s=5.0, poll_interval_s=0.01)
    assert out == {"answer": "OK"}


def test_scanned_pdf_detection_and_ocr_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_file = tmp_path / "scan.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%%EOF\n")

    class EmptyReader:
        def load_data(self, file: str):
            return []

    monkeypatch.setattr(data_loader, "PDFReader", lambda: EmptyReader())
    monkeypatch.setattr(
        data_loader,
        "_ocr_pdf",
        lambda path: [{"text": "Hasil OCR halaman 1", "page_label": "1"}],
    )

    items_no_ocr, used_no_ocr = load_and_chunk_with_status(str(pdf_file), enable_ocr=False)
    assert items_no_ocr == []
    assert used_no_ocr is False

    items_ocr, used_ocr = load_and_chunk_with_status(str(pdf_file), enable_ocr=True)
    assert used_ocr is True
    assert items_ocr == [{"text": "Hasil OCR halaman 1", "page_label": "1"}]


def test_parent_child_chunking_splits_long_text(tmp_path: Path) -> None:
    long_file = tmp_path / "long.txt"
    paragraph = "RAGMON mendukung parent-child chunking untuk menjaga konteks tetap utuh. " * 25
    long_file.write_text(paragraph, encoding="utf-8")

    items, used_ocr = load_and_chunk_with_status(str(long_file))
    assert used_ocr is False
    assert len(items) > 1
    assert all(len(it["parent_text"]) >= len(it["text"]) for it in items)

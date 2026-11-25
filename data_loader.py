from functools import lru_cache
from pathlib import Path
import shutil

from docx import Document
from llama_index.core.node_parser import SentenceSplitter
from llama_index.readers.file import PDFReader
import pypdfium2 as pdfium
import pytesseract
from sentence_transformers import SentenceTransformer

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
PARENT_CHUNK_SIZE = 1500
PARENT_CHUNK_OVERLAP = 200
CHILD_CHUNK_SIZE = 350
CHILD_CHUNK_OVERLAP = 60
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}

_parent_splitter = SentenceSplitter(
    chunk_size=PARENT_CHUNK_SIZE,
    chunk_overlap=PARENT_CHUNK_OVERLAP,
)
_child_splitter = SentenceSplitter(
    chunk_size=CHILD_CHUNK_SIZE,
    chunk_overlap=CHILD_CHUNK_OVERLAP,
)


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    """Lazy-load model embedding lokal sekali saja agar hemat memori."""
    return SentenceTransformer(EMBED_MODEL_NAME)


def _extract_docx_text(path: Path) -> str:
    doc = Document(str(path))
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                parts.append(row_text)
    return "\n".join(parts)


def _split_parent_child(text: str, page_label: str) -> list[dict[str, str]]:
    """Memecah teks menjadi parent block (1500 char) dan child chunk (350 char) untuk retrieval presisi."""
    items: list[dict[str, str]] = []
    for parent_text in _parent_splitter.split_text(text):
        children = _child_splitter.split_text(parent_text) or [parent_text]
        for child_text in children:
            items.append(
                {
                    "text": child_text,
                    "parent_text": parent_text,
                    "page_label": page_label,
                }
            )
    return items


def _ocr_pdf(file_path: Path) -> list[dict[str, str]]:
    """Menjalankan Tesseract OCR per halaman untuk PDF hasil scan tanpa layer teks."""
    if not shutil.which("tesseract"):
        raise RuntimeError("Tesseract OCR tidak ditemukan di sistem.")

    items: list[dict[str, str]] = []
    pdf = pdfium.PdfDocument(str(file_path))
    try:
        for idx in range(len(pdf)):
            page = pdf[idx]
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            text = pytesseract.image_to_string(pil_image).strip()
            if text:
                items.extend(_split_parent_child(text, str(idx + 1)))
    finally:
        pdf.close()
    return items


def load_and_chunk_with_status(path: str, enable_ocr: bool = False) -> tuple[list[dict[str, str]], bool]:
    """Membaca dokumen (.pdf, .txt, .md, .docx) dan mengembalikan (parent-child items, used_ocr)."""
    file_path = Path(path)
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Format file tidak didukung: {ext}")

    items: list[dict[str, str]] = []
    used_ocr = False

    if ext == ".pdf":
        docs = PDFReader().load_data(file=str(file_path))
        for idx, doc in enumerate(docs):
            text = getattr(doc, "text", None)
            if not text or not text.strip():
                continue
            meta = getattr(doc, "metadata", {}) or {}
            page_label = str(meta.get("page_label") or (idx + 1))
            items.extend(_split_parent_child(text, page_label))
        if not items and enable_ocr:
            items = _ocr_pdf(file_path)
            used_ocr = True
    elif ext in {".txt", ".md"}:
        content = file_path.read_text(encoding="utf-8", errors="ignore").strip()
        if content:
            items.extend(_split_parent_child(content, ""))
    else:
        content = _extract_docx_text(file_path).strip()
        if content:
            items.extend(_split_parent_child(content, ""))

    return items, used_ocr


def load_and_chunk_file_with_metadata(path: str, enable_ocr: bool = False) -> list[dict[str, str]]:
    """Membaca dokumen (.pdf, .txt, .md, .docx) dan mengembalikan chunk beserta metadata."""
    items, _ = load_and_chunk_with_status(path, enable_ocr=enable_ocr)
    return items


def load_and_chunk_file(path: str) -> list[str]:
    """Membaca dokumen (.pdf, .txt, .md, .docx) dan memecah teks menjadi chunks."""
    return [item["text"] for item in load_and_chunk_file_with_metadata(path)]


def load_and_chunk_pdf(path: str) -> list[str]:
    """Alias kompatibilitas untuk load_and_chunk_file."""
    return load_and_chunk_file(path)


def embed_text(texts: list[str]) -> list[list[float]]:
    """Mengubah daftar teks menjadi vektor embedding 384-dimensi."""
    if not texts:
        return []
    embedder = _get_embedder()
    vectors = embedder.encode(texts, normalize_embeddings=True)
    return vectors.tolist()

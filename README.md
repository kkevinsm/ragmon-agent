# RAGMON — Production-Ready PDF RAG AI Agent

Aplikasi tanya-jawab dokumen PDF berbasis AI dengan arsitektur *event-driven* dan *durable execution*, dilengkapi **Chat History**, **Daftar PDF Terindeks**, dan asisten berpersona **Anime Girl (Mon-chan)**.

## Tech Stack
- **Orkestrasi & Observability:** Inngest (`inngest` + `inngest-cli`)
- **Backend API:** FastAPI + Uvicorn
- **Vector Database:** Qdrant (Docker)
- **PDF Parsing & Chunking:** LlamaIndex (`PDFReader`, `SentenceSplitter`)
- **Embedding Lokal:** SentenceTransformers (`BAAI/bge-small-en-v1.5`, 384-d)
- **LLM:** Gemini CLI OAuth (`gemini -p` headless mode)
- **Frontend UI:** Streamlit

## Cara Menjalankan

### Cara Cepat (1 Perintah)
```bash
./start.sh
```
Tekan `Ctrl+C` untuk menghentikan seluruh service sekaligus.

### Cara Manual (3 Terminal Terpisah)

#### 1. Pastikan Qdrant (Docker) Menyala
```bash
docker compose up -d
```

### 2. Terminal 1 — Jalankan FastAPI Backend
```bash
uv run uvicorn main:app --reload --port 8000
```

### 3. Terminal 2 — Jalankan Inngest Dev Server
```bash
npx inngest-cli@latest dev -u http://127.0.0.1:8000/api/inngest --no-discovery
```
Dashboard Inngest tersedia di `http://localhost:8288`.

### 4. Terminal 3 — Jalankan Streamlit UI
```bash
uv run streamlit run streamlit_app.py
```

## Catatan Model Gemini CLI
Secara default `main.py` memanggil `gemini -p ... -o json`. Jika model default Gemini CLI mengalami batas kuota harian (429), atur `GEMINI_MODEL` di `.env` ke model lain yang tersedia di akun Gemini CLI kamu.

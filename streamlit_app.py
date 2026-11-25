import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time

from dotenv import load_dotenv
import inngest
import requests
import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from ai_engine import detect_provider
from vector_db import QdrantStorage

load_dotenv()

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _get_monchan_avatar() -> str:
    for ext in ("png", "jpg", "jpeg", "webp"):
        candidate = ASSETS_DIR / f"monchan.{ext}"
        if candidate.exists():
            return str(candidate)
    return ":material/local_florist:"

# Jangan ada baris kosong di dalam <style>: parser Markdown Streamlit memutus blok CSS di baris kosong.
APP_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@400;500;600;700&family=Silkscreen:wght@400;700&display=swap');
.stApp {
    --px-violet: #6d28d9;
    --px-magenta: #db4c8f;
    --px-peach: #ea8c55;
    --px-accent: color-mix(in srgb, #db4c8f 65%, currentColor);
    --px-border: color-mix(in srgb, currentColor 72%, transparent);
    --px-shadow: color-mix(in srgb, currentColor 38%, transparent);
    --px-card: color-mix(in srgb, currentColor 7%, transparent);
    --px-user-card: color-mix(in srgb, #db4c8f 18%, transparent);
    overflow-x: hidden;
}
html, body, .stApp, .stMarkdown, p, li, label, input, textarea,
[data-testid="stChatMessage"] p,
[data-testid="stChatInput"] textarea,
[data-testid="stCaptionContainer"] {
    font-family: 'Pixelify Sans', 'Silkscreen', monospace !important;
}
h1, h2, h3, h4, .ragmon-title, .ragmon-tag, .source-chip, .stButton > button {
    font-family: 'Silkscreen', monospace !important;
    letter-spacing: 0.02em;
}
[data-testid="stAppViewContainer"] {
    background-image:
        radial-gradient(circle at 2px 2px, color-mix(in srgb, currentColor 6%, transparent) 1px, transparent 0),
        linear-gradient(
            180deg,
            rgba(109, 40, 217, 0.22) 0%,
            rgba(219, 76, 143, 0.18) 38%,
            rgba(234, 140, 85, 0.14) 72%,
            rgba(254, 243, 199, 0.08) 100%
        ) !important;
    background-size: 8px 8px, 100% 100% !important;
}
[data-testid="stHeader"] {
    background: transparent !important;
}
[data-testid="stSidebar"] {
    border-right: 3px solid var(--px-border) !important;
}
.ragmon-hero {
    background: var(--px-card);
    border: 2px solid var(--px-border);
    border-radius: 0px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 1.25rem;
    box-shadow: 5px 5px 0px var(--px-shadow);
}
.ragmon-title {
    font-size: clamp(1.1rem, 2.3vw, 1.5rem);
    font-weight: 700;
    margin: 0 0 0.45rem 0;
    line-height: 1.3;
}
.ragmon-accent {
    color: var(--px-accent);
}
.ragmon-sub {
    font-size: 0.9rem;
    color: color-mix(in srgb, currentColor 82%, transparent);
    margin: 0;
}
.ragmon-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-top: 0.85rem;
}
.ragmon-tag {
    display: inline-flex;
    align-items: center;
    font-size: 0.7rem;
    font-weight: 400;
    background: var(--px-card);
    border: 2px solid var(--px-border);
    border-radius: 0px;
    padding: 0.22rem 0.55rem;
    box-shadow: 2px 2px 0px var(--px-shadow);
}
[data-testid="stChatMessage"] {
    background: var(--px-card) !important;
    border: 2px solid var(--px-border) !important;
    border-radius: 0px !important;
    padding: 0.95rem 1.15rem !important;
    box-shadow: 4px 4px 0px var(--px-shadow) !important;
    transition: transform 0.1s steps(2), box-shadow 0.1s steps(2);
    width: fit-content;
    max-width: min(75%, 820px);
}
[data-testid="stChatMessage"] [data-testid^="stChatMessageAvatar"] {
    width: 44px !important;
    height: 44px !important;
    min-width: 44px !important;
    min-height: 44px !important;
}
[data-testid="stChatMessage"] img {
    width: 44px !important;
    height: 44px !important;
    image-rendering: pixelated;
    object-fit: cover;
    border: 2px solid var(--px-border);
    border-radius: 0px !important;
}
[data-testid="stChatMessage"]:hover {
    transform: translate(-1px, -1px);
    box-shadow: 5px 5px 0px var(--px-accent) !important;
}
[class*="st-key-msg-user-"] [data-testid="stChatMessage"] {
    margin-left: auto !important;
    background: var(--px-user-card) !important;
    border: 2px solid var(--px-accent) !important;
}
[class*="st-key-msg-user-"] [data-testid^="stChatMessageAvatar"],
[class*="st-key-msg-bot-"] [data-testid^="stChatMessageAvatar"] {
    display: none !important;
}
[class*="st-key-msg-bot-"] [data-testid="stImage"] {
    width: 44px !important;
    min-width: 44px !important;
    flex: 0 0 44px !important;
}
[class*="st-key-msg-bot-"] [data-testid="stImage"] img {
    width: 44px !important;
    height: 44px !important;
    image-rendering: pixelated;
    object-fit: cover;
    border: 2px solid var(--px-border);
    border-radius: 0px !important;
    box-shadow: 3px 3px 0px var(--px-shadow);
}
}
[class*="st-key-msg-"] {
    gap: 0.3rem !important;
    margin-bottom: 0.45rem;
}
[class*="st-key-act-"] {
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s steps(2);
    gap: 0.35rem !important;
}
[class*="st-key-msg-"]:hover [class*="st-key-act-"],
[class*="st-key-msg-"]:focus-within [class*="st-key-act-"] {
    opacity: 1;
    pointer-events: auto;
}
[class*="st-key-act-"] .stButton > button {
    min-height: 36px !important;
    min-width: 36px !important;
    padding: 0.25rem 0.5rem !important;
    border-radius: 0px !important;
    background: var(--px-card) !important;
    border: 2px solid var(--px-border) !important;
    box-shadow: 2px 2px 0px var(--px-shadow) !important;
}
[class*="st-key-act-"] .stButton > button:hover {
    background: rgba(219, 76, 143, 0.20) !important;
    border-color: var(--px-accent) !important;
}
.source-chip {
    display: inline-flex;
    align-items: center;
    font-size: 0.7rem;
    font-weight: 400;
    color: var(--px-accent);
    background: rgba(219, 76, 143, 0.14);
    border: 2px solid var(--px-accent);
    border-radius: 0px;
    padding: 0.2rem 0.5rem;
    margin: 0.35rem 0.3rem 0 0;
}
.pdf-item {
    background: var(--px-card);
    border: 2px solid var(--px-border);
    border-radius: 0px;
    padding: 0.48rem 0.7rem;
    margin-bottom: 0.42rem;
    font-size: 0.84rem;
    word-break: break-word;
    box-shadow: 2px 2px 0px var(--px-shadow);
}
.status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.82rem;
    padding: 0.34rem 0.6rem;
    margin-bottom: 0.32rem;
    border-radius: 0px;
    background: var(--px-card);
    border: 2px solid var(--px-border);
}
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.72rem;
    font-weight: 600;
}
.status-dot-on {
    width: 8px;
    height: 8px;
    border-radius: 0px;
    background: #10b981;
}
.status-dot-off {
    width: 8px;
    height: 8px;
    border-radius: 0px;
    background: #ef4444;
}
.stButton > button {
    min-height: 44px;
    cursor: pointer !important;
    background-color: var(--px-card) !important;
    border: 2px solid var(--px-border) !important;
    border-radius: 0px !important;
    font-size: 0.78rem !important;
    font-weight: 400 !important;
    box-shadow: 3px 3px 0px var(--px-shadow) !important;
    transition: transform 0.1s steps(2), background-color 0.1s steps(2) !important;
}
.stButton > button:hover {
    border-color: var(--px-accent) !important;
    background-color: rgba(219, 76, 143, 0.16) !important;
    transform: translate(-1px, -1px);
}
.stButton > button:active {
    transform: translate(2px, 2px);
    box-shadow: 1px 1px 0px var(--px-shadow) !important;
}
.stButton > button:disabled {
    cursor: not-allowed !important;
    opacity: 0.55;
}
.stButton > button:focus-visible {
    outline: 2px solid var(--px-accent) !important;
    outline-offset: 2px !important;
}
[data-testid="stChatInput"] textarea:focus,
[data-testid="stChatInput"] textarea:focus-visible {
    outline: none !important;
    box-shadow: none !important;
}
[data-testid="stChatInput"] > div:focus-within {
    border-color: var(--px-accent) !important;
}
[data-testid="stFileUploaderDropzone"] {
    background: var(--px-card) !important;
    border: 2px dashed var(--px-border) !important;
    border-radius: 0px !important;
}
[data-testid="stMainBlockContainer"] {
    padding-bottom: 5.5rem !important;
}
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {
    background: transparent !important;
    border-top: none !important;
}
div[data-testid="stElementContainer"]:has(iframe[title*="streamlit_js_eval"]) {
    display: none !important;
}
/* Pertahankan fill solid bawaan stChatInput agar teks di belakang kotak input tidak tembus */
[data-testid="stChatInput"] {
    border: 2px solid var(--px-border) !important;
    border-radius: 0px !important;
    box-shadow: 4px 4px 0px var(--px-shadow) !important;
}
[data-testid="stChatInput"] > div {
    border: none !important;
    border-radius: 0px !important;
    box-shadow: none !important;
}
@media (max-width: 640px) {
    .ragmon-hero {
        padding: 1rem 1.1rem;
    }
    [data-testid="stChatMessage"] {
        max-width: 92%;
    }
}
@media (hover: none) {
    [class*="st-key-act-"] {
        opacity: 1;
        pointer-events: auto;
    }
}
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        transition: none !important;
        animation: none !important;
    }
}
</style>"""

INITIAL_GREETING = {
    "role": "assistant",
    "content": (
        "Yahallo, Senpai~! Aku **Mon-chan**, asisten PDF pribadimu di **RAGMON**. "
        "Upload file PDF di sidebar kiri dulu ya, lalu tanyakan apa saja tentang isinya supaya kubantu carikan jawabannya."
    ),
    "sources": [],
}


def _get_inngest_client() -> inngest.Inngest:
    return inngest.Inngest(app_id="ragmon", is_production=False)


def _inngest_api_base() -> str:
    return os.getenv("INNGEST_API_BASE", "http://127.0.0.1:8288/v1").rstrip("/")


def _send_event(event_name: str, data: dict) -> str:
    client = _get_inngest_client()
    res = asyncio.run(client.send(inngest.Event(name=event_name, data=data)))
    if isinstance(res, list) and res:
        return str(res[0])
    return str(res)


def _poll_run_output(event_id: str, timeout_s: float = 120.0, poll_interval_s: float = 0.6) -> dict:
    url = f"{_inngest_api_base()}/events/{event_id}/runs"
    deadline = time.time() + timeout_s
    last_status = None

    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            runs = resp.json().get("data", [])
        except requests.RequestException:
            runs = []

        if runs:
            run = runs[0]
            status = str(run.get("status", "")).lower()
            last_status = status
            if status in {"completed", "succeeded", "success", "finished"}:
                if run.get("ended_at") is not None or run.get("output") is not None:
                    return run.get("output") or {}
            if status in {"failed", "cancelled", "canceled"}:
                raise RuntimeError(f"Proses gagal di Inngest (status={status}): {run.get('output')}")

        time.sleep(poll_interval_s)

    raise TimeoutError(f"Timeout menunggu hasil dari Inngest (last_status={last_status}).")


def _check_http_ok(url: str) -> bool:
    try:
        resp = requests.get(url, timeout=1.5)
        return resp.status_code < 400
    except requests.RequestException:
        return False


def _get_services_status() -> list[tuple[str, bool]]:
    fastapi_ok = _check_http_ok("http://127.0.0.1:8000/health")
    inngest_base = _inngest_api_base().removesuffix("/v1")
    inngest_ok = _check_http_ok(f"{inngest_base}/")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333").strip()
    if not qdrant_url or qdrant_url.lower() == "local":
        qdrant_ok = True
    else:
        qdrant_ok = _check_http_ok(qdrant_url.rstrip("/") + "/")
    return [("FastAPI", fastapi_ok), ("Inngest", inngest_ok), ("Qdrant", qdrant_ok)]


def _load_indexed_doc_stats() -> list[dict]:
    try:
        return QdrantStorage().get_source_stats()
    except Exception as exc:
        st.sidebar.warning(f"Belum bisa terhubung ke Qdrant: {exc}")
        return []


@st.dialog("Preview Dokumen")
def _open_preview_dialog(source_id: str, chunk_count: int) -> None:
    st.markdown(f"**`{source_id}`** · Total: **{chunk_count} chunks**")
    try:
        excerpts = QdrantStorage().preview_source(source_id, limit=3)
    except Exception as exc:
        st.error(f"Gagal memuat preview: {exc}")
        return
    if not excerpts:
        st.info("Tidak ada cuplikan teks yang tersedia untuk dokumen ini.")
        return
    for idx, ex in enumerate(excerpts, start=1):
        page_label = ex.get("page_label", "")
        page_tag = f" (Hal. {page_label})" if page_label else ""
        st.markdown(f"**Cuplikan #{idx}{page_tag}**")
        st.caption(ex.get("text", ""))
        if idx < len(excerpts):
            st.divider()


def _delete_indexed_doc(source_id: str) -> None:
    QdrantStorage().delete_by_source(source_id)
    file_path = UPLOAD_DIR / source_id
    if file_path.exists() and file_path.is_file():
        file_path.unlink()
    if "source_filters" in st.session_state:
        st.session_state.source_filters = [
            s for s in st.session_state.source_filters if s != source_id
        ]


def _render_sources(sources: list[str]) -> None:
    if not sources:
        return
    chips = "".join(f"<span class='source-chip'>{s}</span>" for s in sources)
    st.markdown(chips, unsafe_allow_html=True)


def _render_evidences(evidences: list[dict]) -> None:
    if not evidences:
        return
    with st.expander(f"Lihat Bukti Kutipan ({len(evidences)} potongan)"):
        for idx, ev in enumerate(evidences, start=1):
            src = ev.get("source", "Dokumen")
            page_label = str(ev.get("page_label", "") or "").strip()
            page_tag = f" (Hal. {page_label})" if page_label else ""
            score_pct = round(float(ev.get("score", 0.0)) * 100, 1)
            sem_pct = round(float(ev.get("semantic_score", 0.0)) * 100, 1)
            kw_pct = round(float(ev.get("keyword_score", 0.0)) * 100, 1)
            excerpt = str(ev.get("text", "")).strip()
            st.markdown(
                f"**#{idx} `{src}`{page_tag}** | Skor Hybrid: **{score_pct}%** "
                f"(Semantik: {sem_pct}%, Kata Kunci: {kw_pct}%)"
            )
            st.caption(excerpt)
            if idx < len(evidences):
                st.divider()


def _save_undo_snapshot() -> None:
    st.session_state.undo_stack.append([dict(m) for m in st.session_state.messages])


def _delete_message(idx: int) -> None:
    msgs = st.session_state.messages
    if idx <= 0 or idx >= len(msgs):
        return
    _save_undo_snapshot()
    # Menghapus pertanyaan user ikut menghapus balasan Mon-chan pasangannya agar riwayat tetap berpasangan.
    if msgs[idx]["role"] == "user" and idx + 1 < len(msgs) and msgs[idx + 1]["role"] == "assistant":
        del msgs[idx : idx + 2]
    else:
        del msgs[idx]
    st.session_state.editing_idx = None


def _undo_last_action() -> None:
    if st.session_state.undo_stack:
        st.session_state.messages = st.session_state.undo_stack.pop()
        st.session_state.editing_idx = None


def _copy_to_clipboard(text: str) -> None:
    # pbcopy menyalin ke clipboard mesin server; aplikasi ini berjalan lokal di macOS yang sama dengan browser.
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
        st.toast("Teks disalin ke clipboard")
    except Exception:
        st.toast("Gagal menyalin teks ke clipboard")


def _export_chat_markdown(messages: list[dict]) -> str:
    """Mengubah riwayat percakapan beserta sumber dan bukti kutipan menjadi dokumen Markdown."""
    lines = [
        "# RAGMON Chat Export",
        f"_Diekspor pada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
    ]
    for msg in messages:
        speaker = "User" if msg.get("role") == "user" else "Mon-chan"
        lines.append(f"## {speaker}")
        lines.append(str(msg.get("content", "")).strip())
        sources = msg.get("sources") or []
        if sources:
            lines.append("")
            lines.append("**Sumber:** " + ", ".join(f"`{s}`" for s in sources))
        evidences = msg.get("evidences") or []
        if evidences:
            lines.append("")
            lines.append("**Bukti Kutipan:**")
            for idx, ev in enumerate(evidences, start=1):
                src = ev.get("source", "Dokumen")
                page_label = str(ev.get("page_label", "") or "").strip()
                page_tag = f" (Hal. {page_label})" if page_label else ""
                score_pct = round(float(ev.get("score", 0.0)) * 100, 1)
                excerpt = str(ev.get("text", "")).strip().replace("\n", " ")
                lines.append(f"- **#{idx} `{src}`{page_tag} ({score_pct}%)**: {excerpt}")
        lines.extend(["", "---", ""])
    return "\n".join(lines)


def _query_monchan(
    question: str,
    top_k: int,
    history_slice: list[dict],
    source_filters: list[str] | None = None,
    custom_api_key: str = "",
) -> tuple[str, list[str], list[dict], str, str]:
    history_payload = [{"role": m["role"], "content": m["content"]} for m in history_slice]
    event_id = _send_event(
        "rag/query_pdf_ai",
        {
            "question": question,
            "top_k": top_k,
            "chat_history": history_payload,
            "source_filters": source_filters or [],
            "custom_api_key": custom_api_key,
        },
    )
    output = _poll_run_output(event_id, timeout_s=180.0)
    if not isinstance(output, dict) or not output.get("answer"):
        raise RuntimeError(f"Output model kosong atau tidak valid: {output}")
    answer = str(output["answer"])
    sources = output.get("sources", [])
    evidences = output.get("evidences", [])
    provider = output.get("provider", "")
    model = output.get("model", "")
    return answer, sources, evidences, provider, model


@st.dialog("Pengaturan API Key (BYOK)")
def _open_byok_dialog() -> None:
    st.caption(
        "Masukkan API Key milikmu sendiri (opsional). Jika dikosongkan, RAGMON memakai "
        "API key di `.env` atau Gemini CLI OAuth lokal."
    )
    key_input = st.text_input(
        "API Key",
        value=st.session_state.get("custom_api_key", ""),
        type="password",
        placeholder="AIza... / sk-... / sk-ant-... / xai-...",
    )
    detected = detect_provider(key_input) if key_input.strip() else None

    providers_meta = [
        ("gemini", "Google Gemini", "AIza", "https://aistudio.google.com/apikey"),
        ("openai", "OpenAI", "sk-", "https://platform.openai.com/api-keys"),
        ("anthropic", "Anthropic Claude", "sk-ant-", "https://console.anthropic.com/settings/keys"),
        ("xai", "xAI Grok", "xai-", "https://console.x.ai"),
    ]
    c1, c2 = st.columns(2)
    for idx, (pid, label, prefix, url) in enumerate(providers_meta):
        target_col = c1 if idx % 2 == 0 else c2
        active = detected == pid
        border_col = "var(--px-accent)" if active else "var(--px-border)"
        bg_col = "rgba(219, 76, 143, 0.16)" if active else "var(--background-color)"
        badge = " [AKTIF]" if active else ""
        with target_col:
            st.markdown(
                f"<div style='border:2px solid {border_col};background:{bg_col};padding:0.45rem 0.6rem;margin-bottom:0.45rem;'>"
                f"<strong>{label}{badge}</strong><br/>"
                f"<span style='font-size:0.78rem;'>Prefix: <code>{prefix}</code> · "
                f"<a href='{url}' target='_blank'>Buat Key</a></span></div>",
                unsafe_allow_html=True,
            )

    b_save, b_del = st.columns(2)
    with b_save:
        if st.button("Simpan Key", icon=":material/save:", use_container_width=True):
            cleaned_key = key_input.strip()
            st.session_state.custom_api_key = cleaned_key
            st.session_state.ls_pending_op = ("set", cleaned_key) if cleaned_key else ("remove", "")
            st.session_state.ls_op_seq += 1
            st.toast("API Key disimpan di browser (localStorage)")
            st.rerun()
    with b_del:
        if st.button("Hapus Key", icon=":material/delete_outline:", use_container_width=True):
            st.session_state.custom_api_key = ""
            st.session_state.ls_pending_op = ("remove", "")
            st.session_state.ls_op_seq += 1
            st.toast("API Key dihapus dari browser")
            st.rerun()


def _render_user_message(idx: int, content: str) -> None:
    with st.container(key=f"msg-user-{idx}"):
        with st.chat_message("user", avatar=":material/person:"):
            if st.session_state.editing_idx == idx:
                edited = st.text_area(
                    "Edit pertanyaan",
                    value=content,
                    key=f"edit-input-{idx}",
                    label_visibility="collapsed",
                )
                with st.container(horizontal=True, gap="small"):
                    if st.button("Kirim Ulang", icon=":material/send:", key=f"save-edit-{idx}"):
                        cleaned = edited.strip()
                        if cleaned:
                            _save_undo_snapshot()
                            st.session_state.messages = st.session_state.messages[:idx]
                            st.session_state.messages.append({"role": "user", "content": cleaned, "sources": []})
                            st.session_state.editing_idx = None
                            st.session_state.pending_query = cleaned
                            st.rerun()
                    if st.button("Batal", icon=":material/close:", key=f"cancel-edit-{idx}"):
                        st.session_state.editing_idx = None
                        st.rerun()
            else:
                st.markdown(content)

        if st.session_state.editing_idx != idx:
            with st.container(key=f"act-user-{idx}", horizontal=True, horizontal_alignment="right", gap="small"):
                if st.button("", icon=":material/delete_outline:", key=f"del-{idx}", help="Hapus"):
                    _delete_message(idx)
                    st.rerun()
                if st.button("", icon=":material/content_copy:", key=f"copy-{idx}", help="Copy"):
                    _copy_to_clipboard(content)
                if st.button("", icon=":material/edit:", key=f"edit-{idx}", help="Edit perintah"):
                    st.session_state.editing_idx = idx
                    st.rerun()


def _render_bot_message(
    idx: int,
    content: str,
    sources: list[str],
    evidences: list[dict],
    provider: str = "",
    model: str = "",
) -> None:
    with st.container(key=f"msg-bot-{idx}"):
        with st.container(horizontal=True, vertical_alignment="top", wrap=False, gap="small"):
            avatar = _get_monchan_avatar()
            if not avatar.startswith(":material/"):
                st.image(avatar, width=44)
            with st.chat_message("assistant"):
                st.markdown(content)
                _render_sources(sources)
                if provider and provider != "none":
                    st.caption(f"Model: {provider} / {model}")
                _render_evidences(evidences)

        if idx > 0:
            with st.container(key=f"act-bot-{idx}", horizontal=True, horizontal_alignment="left", gap="small"):
                if st.button("", icon=":material/delete_outline:", key=f"del-{idx}", help="Hapus"):
                    _delete_message(idx)
                    st.rerun()
                if st.button("", icon=":material/content_copy:", key=f"copy-{idx}", help="Copy"):
                    _copy_to_clipboard(content)


st.set_page_config(
    page_title="RAGMON: Document RAG Assistant",
    page_icon=":material/description:",
    layout="wide",
)
st.markdown(APP_CSS, unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = [dict(INITIAL_GREETING)]
if "undo_stack" not in st.session_state:
    st.session_state.undo_stack = []
if "editing_idx" not in st.session_state:
    st.session_state.editing_idx = None
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None
if "last_ingested_doc" not in st.session_state:
    st.session_state.last_ingested_doc = None
if "custom_api_key" not in st.session_state:
    st.session_state.custom_api_key = ""
if "ls_loaded" not in st.session_state:
    st.session_state.ls_loaded = False
if "ls_pending_op" not in st.session_state:
    st.session_state.ls_pending_op = None
if "ls_op_seq" not in st.session_state:
    st.session_state.ls_op_seq = 0

if not st.session_state.ls_loaded:
    stored_key = streamlit_js_eval(
        js_expressions="localStorage.getItem('ragmon_api_key') || ''",
        key="ls_load_api_key",
    )
    if stored_key is not None:
        st.session_state.ls_loaded = True
        if str(stored_key).strip() and not st.session_state.custom_api_key:
            st.session_state.custom_api_key = str(stored_key).strip()

if st.session_state.ls_pending_op is not None:
    op, val = st.session_state.ls_pending_op
    if op == "set":
        expr = f"localStorage.setItem('ragmon_api_key', {json.dumps(val)})"
    else:
        expr = "localStorage.removeItem('ragmon_api_key')"
    streamlit_js_eval(js_expressions=expr, key=f"ls_write_{st.session_state.ls_op_seq}")
    st.session_state.ls_pending_op = None

with st.sidebar:
    st.markdown("#### :material/tune: RAGMON Control Panel")

    has_key = bool(st.session_state.custom_api_key.strip())
    key_label = (
        f"API Key: {detect_provider(st.session_state.custom_api_key).upper()}"
        if has_key
        else "Set API Key (BYOK)"
    )
    if st.button(key_label, icon=":material/key:", use_container_width=True):
        _open_byok_dialog()

    st.markdown("**:material/description: Upload Dokumen Baru**")
    uploaded_file = st.file_uploader(
        "Pilih file (.pdf, .txt, .md, .docx)",
        type=["pdf", "txt", "md", "docx"],
    )
    enable_ocr = st.checkbox(
        "Aktifkan OCR untuk PDF hasil scan",
        value=False,
        help="Jalankan Tesseract OCR otomatis jika PDF tidak memiliki layer teks.",
    )
    if uploaded_file is not None:
        if st.button("Proses & Indeks Dokumen", icon=":material/upload_file:", use_container_width=True):
            save_path = UPLOAD_DIR / uploaded_file.name
            save_path.write_bytes(uploaded_file.getbuffer())
            with st.spinner("Mon-chan sedang memotong dan mengindeks dokumen kamu..."):
                try:
                    event_id = _send_event(
                        "rag/ingest_pdf",
                        {
                            "pdf_path": str(save_path),
                            "source_id": uploaded_file.name,
                            "enable_ocr": enable_ocr,
                        },
                    )
                    output = _poll_run_output(event_id, timeout_s=180.0)
                    ingested = int(output.get("ingested", 0))
                    used_ocr = bool(output.get("used_ocr", False))
                    if ingested == 0:
                        st.warning(
                            f"Tidak ada teks yang bisa diekstrak dari `{uploaded_file.name}` "
                            "(kemungkinan PDF hasil scan/gambar atau file kosong). "
                            "Aktifkan opsi OCR di atas lalu proses ulang."
                        )
                    else:
                        st.session_state.last_ingested_doc = uploaded_file.name
                        via = " via OCR" if used_ocr else ""
                        st.success(f"Yatta~! `{uploaded_file.name}` berhasil diindeks{via} ({ingested} chunks).")
                except Exception as exc:
                    st.error(f"Gagal memproses dokumen: {exc}")

    st.divider()

    col_title, col_btn = st.columns([3, 1])
    with col_title:
        st.markdown("**:material/library_books: Dokumen Terindeks**")
    with col_btn:
        if st.button("", icon=":material/refresh:", help="Refresh daftar dokumen"):
            st.rerun()

    doc_stats = _load_indexed_doc_stats()
    indexed_docs = [item["source"] for item in doc_stats]
    if doc_stats:
        for doc_idx, item in enumerate(doc_stats):
            doc_name = item["source"]
            chunk_count = item["chunks"]
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(
                    f"<div class='pdf-item' style='flex:1;margin-bottom:0;'>"
                    f"{doc_name}<br/><span style='font-size:0.74rem;opacity:0.78;'>{chunk_count} chunks</span></div>",
                    unsafe_allow_html=True,
                )
                if st.button("", icon=":material/visibility:", key=f"preview-doc-{doc_idx}", help=f"Preview {doc_name}"):
                    _open_preview_dialog(doc_name, chunk_count)
                if st.button("", icon=":material/delete_outline:", key=f"del-doc-{doc_idx}", help=f"Hapus {doc_name}"):
                    try:
                        _delete_indexed_doc(doc_name)
                        st.toast(f"Dokumen {doc_name} dihapus")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Gagal menghapus {doc_name}: {exc}")
    else:
        st.caption("Belum ada dokumen yang terindeks, Senpai~")

    st.divider()

    st.markdown("**:material/settings: Pengaturan**")
    source_filters = st.multiselect(
        "Filter sumber jawaban",
        options=indexed_docs,
        key="source_filters",
        placeholder="Cari di semua dokumen",
        help="Kosongkan untuk mencari di semua dokumen, atau pilih satu atau beberapa dokumen saja.",
    )
    top_k = st.slider("Jumlah konteks (top_k)", min_value=1, max_value=10, value=5)

    if st.button(
        "Undo Aksi Terakhir",
        icon=":material/undo:",
        use_container_width=True,
        disabled=len(st.session_state.undo_stack) == 0,
    ):
        _undo_last_action()
        st.rerun()

    st.download_button(
        "Export Catatan (.md)",
        data=_export_chat_markdown(st.session_state.messages),
        file_name=f"ragmon-chat-{datetime.now().strftime('%Y%m%d-%H%M')}.md",
        mime="text/markdown",
        icon=":material/download:",
        use_container_width=True,
    )

    if st.button("Hapus Riwayat Chat", icon=":material/delete_sweep:", use_container_width=True):
        _save_undo_snapshot()
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Riwayat chat sudah kubersihkan, Senpai~. Yuk mulai diskusi baru lagi.",
                "sources": [],
            }
        ]
        st.session_state.editing_idx = None
        st.rerun()

    st.divider()

    st.markdown("**:material/monitoring: Status Service**")
    for svc_name, is_up in _get_services_status():
        dot_cls = "status-dot-on" if is_up else "status-dot-off"
        label = "Online" if is_up else "Offline"
        st.markdown(
            f"<div class='status-row'><span>{svc_name}</span>"
            f"<span class='status-pill'><span class='{dot_cls}' aria-hidden='true'></span>{label}</span></div>",
            unsafe_allow_html=True,
        )

st.markdown(
    """<div class="ragmon-hero">
<div class="ragmon-title">RAGMON: Chat bareng <span class="ragmon-accent">Mon-chan</span></div>
<p class="ragmon-sub">Tanya jawab dokumen PDF dengan orkestrasi event-driven dan sitasi sumber otomatis.</p>
<div class="ragmon-meta">
<span class="ragmon-tag">Inngest Orchestration</span>
<span class="ragmon-tag">Qdrant Vector DB</span>
<span class="ragmon-tag">LlamaIndex</span>
<span class="ragmon-tag">Gemini CLI OAuth</span>
</div>
</div>""",
    unsafe_allow_html=True,
)

for idx, msg in enumerate(st.session_state.messages):
    if msg["role"] == "user":
        _render_user_message(idx, msg["content"])
    else:
        _render_bot_message(
            idx,
            msg["content"],
            msg.get("sources") or [],
            msg.get("evidences") or [],
            msg.get("provider", ""),
            msg.get("model", ""),
        )

if st.session_state.pending_query:
    query_text = st.session_state.pending_query
    st.session_state.pending_query = None
    with st.container(key="msg-bot-pending"):
        with st.container(horizontal=True, vertical_alignment="top", wrap=False, gap="small"):
            avatar = _get_monchan_avatar()
            if not avatar.startswith(":material/"):
                st.image(avatar, width=44)
            with st.chat_message("assistant"):
                with st.spinner("Mon-chan sedang membaca catatan PDF untuk Senpai..."):
                    try:
                        answer, sources, evidences, provider, model = _query_monchan(
                            query_text,
                            top_k,
                            st.session_state.messages[:-1],
                            source_filters,
                            st.session_state.custom_api_key,
                        )
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": answer,
                                "sources": sources,
                                "evidences": evidences,
                                "provider": provider,
                                "model": model,
                            }
                        )
                    except Exception as exc:
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": f"Ada error saat memproses pertanyaan: `{exc}`",
                                "sources": [],
                                "evidences": [],
                            }
                        )
    st.rerun()

if indexed_docs:
    target_label = st.session_state.last_ingested_doc or "dokumen terindeks"
    quick_prompts = [
        f"Ringkas {target_label} ini",
        "Apa poin utamanya?",
        "Buat daftar istilah penting",
    ]
    with st.container(horizontal=True, gap="small"):
        for q_idx, qp in enumerate(quick_prompts):
            if st.button(qp, key=f"quick-prompt-{q_idx}"):
                _save_undo_snapshot()
                st.session_state.messages.append({"role": "user", "content": qp, "sources": []})
                st.session_state.pending_query = qp
                st.session_state.last_ingested_doc = None
                st.rerun()

if prompt := st.chat_input("Tanya sesuatu ke Mon-chan tentang PDF kamu..."):
    _save_undo_snapshot()
    st.session_state.messages.append({"role": "user", "content": prompt, "sources": []})
    st.session_state.pending_query = prompt
    st.rerun()

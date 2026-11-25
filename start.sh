#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PIDS=()

cleanup() {
  echo ""
  echo "🛑 Menghentikan seluruh service RAGMON..."
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  echo "✅ Semua service berhenti."
}

trap cleanup EXIT INT TERM

echo "🐳 Memastikan container Qdrant menyala..."
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker compose up -d
else
  echo "⚠️  Docker daemon tidak terdeteksi/belum menyala. Pastikan Qdrant berjalan atau atur QDRANT_URL=local di .env."
fi

echo "🚀 Menjalankan FastAPI (port 8000)..."
uv run uvicorn main:app --port 8000 &
PIDS+=($!)

for _ in {1..30}; do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo "⚡ Menjalankan Inngest Dev Server (port 8288)..."
npx inngest-cli@latest dev -u http://127.0.0.1:8000/api/inngest --no-discovery &
PIDS+=($!)

sleep 2

echo "🌸 Menjalankan Streamlit UI (port 8501)..."
echo "   - Streamlit UI : http://localhost:8501"
echo "   - Inngest UI   : http://localhost:8288"
echo "   - FastAPI Docs : http://localhost:8000/docs"
echo "   Tekan Ctrl+C untuk menghentikan semua service sekaligus."
echo ""

uv run streamlit run streamlit_app.py --server.headless true &
PIDS+=($!)

wait

import json
import os
import subprocess
import time
from typing import Any

import requests

_GEMINI_CACHE: dict[str, tuple[float, list[str]]] = {}
_GEMINI_CACHE_TTL_S = 300.0
_DEFAULT_GEMINI_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]

PROVIDER_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"],
    "anthropic": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
    "xai": ["grok-3-mini", "grok-2-latest"],
}


def detect_provider(api_key: str, explicit_provider: str | None = None) -> str:
    """Mendeteksi provider AI dari prefix API key atau pilihan eksplisit."""
    if explicit_provider and explicit_provider.strip():
        return explicit_provider.strip().lower()
    key = api_key.strip()
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("xai-"):
        return "xai"
    if key.startswith("sk-"):
        return "openai"
    return "gemini"


def resolve_api_key(custom_api_key: str | None = None, explicit_provider: str | None = None) -> tuple[str, str]:
    """Mengambil API key dari input BYOK atau fallback ke environment variable server."""
    if custom_api_key and custom_api_key.strip():
        key = custom_api_key.strip()
        return key, detect_provider(key, explicit_provider)

    env_order = [
        ("GEMINI_API_KEY", "gemini"),
        ("OPENAI_API_KEY", "openai"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("XAI_API_KEY", "xai"),
    ]
    if explicit_provider:
        target = explicit_provider.strip().lower()
        env_order.sort(key=lambda pair: 0 if pair[1] == target else 1)

    for env_name, prov in env_order:
        val = os.getenv(env_name, "").strip()
        if val:
            return val, prov

    return "", "gemini-cli"


def resolve_gemini_models(api_key: str) -> list[str]:
    """Mengambil daftar model gemini-*-flash terbaru dari API Gemini dengan cache & fallback."""
    now = time.time()
    cached = _GEMINI_CACHE.get(api_key)
    if cached and (now - cached[0]) < _GEMINI_CACHE_TTL_S:
        return cached[1]

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    excluded = ("embedding", "imagen", "tts", "audio", "transcribe")
    try:
        resp = requests.get(url, timeout=3.5)
        resp.raise_for_status()
        raw_models = resp.json().get("models", [])
        candidates: list[str] = []
        for item in raw_models:
            name = str(item.get("name", "")).removeprefix("models/")
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            low = name.lower()
            if "gemini-" in low and "flash" in low and not any(bad in low for bad in excluded):
                candidates.append(name)
        if candidates:
            candidates.sort(reverse=True)
            _GEMINI_CACHE[api_key] = (now, candidates)
            return candidates
    except requests.RequestException:
        pass

    return list(_DEFAULT_GEMINI_MODELS)


def _call_openai_compatible(
    url: str,
    api_key: str,
    model: str,
    system_instruction: str,
    user_prompt: str,
    timeout_s: float,
) -> requests.Response:
    return requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
        },
        timeout=timeout_s,
    )


def _call_anthropic(
    api_key: str,
    model: str,
    system_instruction: str,
    user_prompt: str,
    timeout_s: float,
) -> requests.Response:
    return requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "system": system_instruction,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.2,
            "max_tokens": 1024,
        },
        timeout=timeout_s,
    )


def _call_gemini_rest(
    api_key: str,
    model: str,
    system_instruction: str,
    user_prompt: str,
    timeout_s: float,
    json_output: bool = False,
) -> requests.Response:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    gen_config: dict[str, Any] = {"temperature": 0.2, "maxOutputTokens": 4096}
    if json_output:
        gen_config["responseMimeType"] = "application/json"

    return requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": gen_config,
        },
        timeout=timeout_s,
    )


def _extract_response_text(provider: str, payload: dict) -> str:
    if provider in {"openai", "xai"}:
        return str(payload["choices"][0]["message"]["content"]).strip()
    if provider == "anthropic":
        parts = payload.get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    candidates = payload.get("candidates", [])
    parts = candidates[0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def call_gemini_cli(prompt: str) -> tuple[str, str, str]:
    """Fallback ke Gemini CLI OAuth lokal saat tidak ada API key BYOK/server."""
    models_to_try: list[str] = []
    env_model = os.getenv("GEMINI_MODEL", "").strip()
    if env_model:
        models_to_try.append(env_model)
    fallback_env = os.getenv("GEMINI_FALLBACK_MODELS", "")
    for item in fallback_env.split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in models_to_try:
            models_to_try.append(cleaned)
    if not models_to_try:
        models_to_try = [""]

    last_err = ""
    for model in models_to_try:
        cmd = ["gemini", "-p", prompt, "-o", "json"]
        if model:
            cmd.extend(["-m", model])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        json_start = stdout.find("{")
        if json_start != -1:
            try:
                payload = json.loads(stdout[json_start:])
                if "error" in payload:
                    last_err = payload["error"].get("message", str(payload["error"]))
                    continue
                if "response" in payload:
                    return str(payload["response"]).strip(), "gemini-cli", model or "default"
            except json.JSONDecodeError:
                pass

        if proc.returncode == 0 and stdout:
            return stdout, "gemini-cli", model or "default"
        last_err = stderr or stdout or f"exit code {proc.returncode}"

    raise RuntimeError(f"Gemini CLI error: {last_err}")


def generate_with_ai(
    system_instruction: str,
    user_prompt: str,
    api_key: str | None = None,
    provider: str | None = None,
    preferred_model: str | None = None,
    timeout_s: float = 25.0,
    json_output: bool = False,
) -> tuple[str, str, str]:
    """Menjalankan inferensi AI dengan auto-detect provider dan auto-failover model."""
    resolved_key, resolved_provider = resolve_api_key(api_key, provider)
    if not resolved_key or resolved_provider == "gemini-cli":
        combined_prompt = f"{system_instruction}\n\n{user_prompt}"
        return call_gemini_cli(combined_prompt)

    if resolved_provider == "gemini":
        candidates = resolve_gemini_models(resolved_key)
    else:
        candidates = list(PROVIDER_MODELS.get(resolved_provider, []))

    if preferred_model and preferred_model.strip():
        pref = preferred_model.strip()
        candidates = [pref] + [m for m in candidates if m != pref]

    last_error = "Tidak ada model kandidat yang tersedia."
    for model in candidates:
        try:
            if resolved_provider == "openai":
                resp = _call_openai_compatible(
                    "https://api.openai.com/v1/chat/completions",
                    resolved_key,
                    model,
                    system_instruction,
                    user_prompt,
                    timeout_s,
                )
            elif resolved_provider == "xai":
                resp = _call_openai_compatible(
                    "https://api.x.ai/v1/chat/completions",
                    resolved_key,
                    model,
                    system_instruction,
                    user_prompt,
                    timeout_s,
                )
            elif resolved_provider == "anthropic":
                resp = _call_anthropic(
                    resolved_key,
                    model,
                    system_instruction,
                    user_prompt,
                    timeout_s,
                )
            else:
                resp = _call_gemini_rest(
                    resolved_key,
                    model,
                    system_instruction,
                    user_prompt,
                    timeout_s,
                    json_output=json_output,
                )
        except requests.RequestException as exc:
            last_error = str(exc)
            continue

        if resp.status_code in {401, 403}:
            raise RuntimeError(
                f"API key untuk provider '{resolved_provider}' tidak valid atau ditolak (HTTP {resp.status_code})."
            )

        if resp.status_code in {404, 429, 500, 502, 503}:
            last_error = f"HTTP {resp.status_code} pada model {model}: {resp.text[:200]}"
            continue

        if not resp.ok:
            last_error = f"HTTP {resp.status_code} pada model {model}: {resp.text[:200]}"
            continue

        text = _extract_response_text(resolved_provider, resp.json())
        if text:
            return text, resolved_provider, model

    raise RuntimeError(f"Semua model untuk '{resolved_provider}' gagal ({last_error}).")

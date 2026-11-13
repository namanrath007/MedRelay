"""
One place to talk to an LLM. Every agent calls ask_json(); nothing else in
the project knows which vendor is behind it.

Configure in .env:
  LLM_PROVIDER=gemini            # gemini | azure | ollama
  GEMINI_API_KEY=...             # gemini
  GEMINI_MODEL=gemini-3.8-flash
  GEMINI_FALLBACK_MODELS=gemini-3.5-flash-lite,gemini-3.7-flash   # used when the main model is busy
  AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_API_KEY=... AZURE_OPENAI_DEPLOYMENT=...   # azure
  OLLAMA_MODEL=llama3.1          # ollama (local, free)
"""
import hashlib
import json
import threading
import os
import re
import time
import urllib.request

from fhirbridge_runtime.env import load_env

load_env(warn=True)

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()


def _parse_json(text: str):
    """Models sometimes wrap JSON in ``` fences; strip them before parsing."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


# Primary model first, then backups used automatically when Google says a model is overloaded
GEMINI_MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.8-flash")] + [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS",
                                 "gemini-3.5-flash-lite,gemini-3.7-flash,gemini-3.5-flash").split(",")
    if m.strip() and m.strip() != os.getenv("GEMINI_MODEL", "gemini-3.8-flash")]
_current = {"i": 0}


def _gemini(prompt: str, system: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client()
    resp = client.models.generate_content(
        model=GEMINI_MODELS[_current["i"]],
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    return resp.text


def _azure(prompt: str, system: str) -> str:
    from openai import AzureOpenAI
    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )
    resp = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return resp.choices[0].message.content


def _ollama(prompt: str, system: str) -> str:
    body = json.dumps({
        "model": os.getenv("OLLAMA_MODEL", "llama3.1"),
        "system": system, "prompt": prompt, "format": "json", "stream": False,
        "options": {"temperature": 0.1},
    }).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["response"]


_BACKENDS = {"gemini": _gemini, "azure": _azure, "ollama": _ollama}


class QuotaExhausted(RuntimeError):
    """Every configured model has used its daily free-tier quota."""


# ---------------------------------------------------------------- cache + call log
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_ROOT, "outputs", ".llm_cache")
CALL_LOG = os.path.join(_ROOT, "outputs", "llm_calls.jsonl")
USE_CACHE = os.getenv("LLM_CACHE", "1") != "0"   # set LLM_CACHE=0 in .env to always call the model
_lock = threading.Lock()


def _cache_key(prompt: str, system: str) -> str:
    raw = json.dumps([PROVIDER, GEMINI_MODELS[0] if PROVIDER == "gemini" else model_name(), system, prompt])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _log_call(seconds: float, prompt: str, cached: bool, ok: bool, label: str):
    os.makedirs(os.path.dirname(CALL_LOG), exist_ok=True)
    with _lock, open(CALL_LOG, "a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": label, "model": model_name(),
                            "seconds": round(seconds, 2), "prompt_chars": len(prompt),
                            "cached": cached, "ok": ok}) + "\n")


def ask_json(prompt: str, system: str = "You are a precise assistant. Reply with JSON only.",
             retries: int = 5, label: str = "", use_cache: bool = True) -> dict:
    """Send a prompt, get parsed JSON back.
    - identical prompt answered before -> returned instantly from outputs/.llm_cache (unless LLM_CACHE=0)
    - model busy (503) -> switch to the next backup model immediately
    - rate limit / bad JSON -> short back-off and retry
    Every call is timed in outputs/llm_calls.jsonl."""
    key = _cache_key(prompt, system)
    path = os.path.join(CACHE_DIR, key + ".json")
    if USE_CACHE and use_cache and os.path.exists(path):
        t0 = time.perf_counter()
        with open(path) as f:
            result = json.load(f)
        _log_call(time.perf_counter() - t0, prompt, cached=True, ok=True, label=label)
        print(f"    [{label or 'llm'}] answered from cache (instant)")
        return result

    backend = _BACKENDS[PROVIDER]
    last_err = None
    t_start = time.perf_counter()
    for attempt in range(1, retries + 1):
        try:
            t0 = time.perf_counter()
            result = _parse_json(backend(prompt, system))
            took = time.perf_counter() - t0
            print(f"    [{label or 'llm'}] {model_name()} answered in {took:.1f}s"
                  + (f" (total incl. retries {time.perf_counter() - t_start:.1f}s)" if attempt > 1 else ""))
            _log_call(time.perf_counter() - t_start, prompt, cached=False, ok=True, label=label)
            if USE_CACHE and use_cache:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(path, "w") as f:
                    json.dump(result, f)
            return result
        except Exception as e:  # rate limit, transient error, or malformed JSON
            last_err = e
            msg = str(e)
            busy = any(t in msg for t in ("503", "UNAVAILABLE", "overloaded", "high demand"))
            # Daily free-tier quota used up: waiting won't help today, but each model has its OWN quota
            daily_quota = "RESOURCE_EXHAUSTED" in msg and ("PerDay" in msg or "per day" in msg)
            with _lock:
                can_switch = PROVIDER == "gemini" and (busy or daily_quota) and _current["i"] < len(GEMINI_MODELS) - 1
                if can_switch:
                    _current["i"] += 1
            if can_switch:
                why = "has used today's free quota" if daily_quota else "is busy"
                print(f"    {GEMINI_MODELS[_current['i'] - 1]} {why} -> switching to {GEMINI_MODELS[_current['i']]}")
                continue
            if daily_quota:
                _log_call(time.perf_counter() - t_start, prompt, cached=False, ok=False, label=label)
                raise QuotaExhausted(
                    "Daily free Gemini quota used up for every configured model "
                    f"({', '.join(GEMINI_MODELS)}). Options: wait for the daily reset, use a teammate's "
                    "API key in .env, add more models to GEMINI_FALLBACK_MODELS, or enable billing.") from e
            wait = 3 * attempt
            print(f"    [{label or 'llm'}] attempt {attempt} failed ({type(e).__name__}: {str(e)[:120]}); retrying in {wait}s")
            time.sleep(wait)
    _log_call(time.perf_counter() - t_start, prompt, cached=False, ok=False, label=label)
    raise RuntimeError(f"LLM failed after {retries} attempts: {last_err}")


def forget(prompt: str, system: str):
    """Remove a cached answer (e.g. generated code that failed validation must not be replayed)."""
    path = os.path.join(CACHE_DIR, _cache_key(prompt, system) + ".json")
    if os.path.exists(path):
        os.remove(path)


def model_name() -> str:
    return {"gemini": GEMINI_MODELS[_current["i"]],
            "azure": os.getenv("AZURE_OPENAI_DEPLOYMENT", "?"),
            "ollama": os.getenv("OLLAMA_MODEL", "llama3.1")}[PROVIDER]

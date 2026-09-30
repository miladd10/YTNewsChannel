from __future__ import annotations

import json
import threading
import time
import uuid

from .local_cli import generate_local_text
from .secrets import get_api_key

# Which pipeline step a call belongs to, recognised from its system prompt.
_TASKS = (
    ("atomic claim ledger", "Claim ledger"),
    ("dry English version", "Voice pairs (one-time)"),
    ("style director", "Style blueprint"),
    ("words one host will say", "Writer"),
    ("final spoken-Persian editor", "Polish"),
    ("factual freshness auditor", "Fact check"),
    ("Audit a completed cinema-news narration", "Claim audit"),
    ("final assembly repair writer", "Repair"),
    ("independent editor", "Reviewer"),
    ("revision writer", "Revision"),
    ("enrichment rewrite writer", "Enrichment rewrite"),
)

_lock = threading.Lock()
_active: dict[str, dict] = {}
_recent: list[dict] = []


def _task_name(system_prompt: str) -> str:
    head = (system_prompt or "")[:400]
    for needle, name in _TASKS:
        if needle.lower() in head.lower():
            return name
    return (head.strip().splitlines() or ["AI call"])[0][:60]


def _log_path():
    from ..db import BASE_DIR
    folder = BASE_DIR / "data" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "ai-calls.jsonl"


def ai_activity() -> dict:
    """Calls running right now and the latest finished ones (for the UI)."""
    now = time.time()
    with _lock:
        running = [
            {**{k: v for k, v in call.items() if k != "started"}, "seconds": round(now - call["started"], 1)}
            for call in _active.values()
        ]
        return {"running": running, "recent": list(_recent[-25:])}


class activity:
    """Track a non-AI wait (web search, article fetch) the same way."""

    def __init__(self, task: str) -> None:
        self.task = task
        self.call_id = str(uuid.uuid4())

    def __enter__(self):
        with _lock:
            _active[self.call_id] = {"task": self.task, "provider": "web", "model": "", "input_chars": 0, "started": time.time()}
        return self

    def __exit__(self, exc_type, exc, tb):
        with _lock:
            entry = _active.pop(self.call_id, None) or {"started": time.time()}
            _recent.append({
                "at": time.strftime("%Y-%m-%d %H:%M:%S"), "ended": time.time(), "task": self.task, "provider": "web", "model": "",
                "seconds": round(time.time() - entry["started"], 1), "input_chars": 0, "output_chars": 0,
                "error": str(exc)[:300] if exc else "",
            })
            del _recent[:-100]
        return False


def generate_text(provider: str, model: str, system_prompt: str, user_prompt: str) -> tuple[str, str, str]:
    call_id = str(uuid.uuid4())
    entry = {
        "task": _task_name(system_prompt), "provider": provider, "model": model,
        "input_chars": len(system_prompt or "") + len(user_prompt or ""), "started": time.time(),
    }
    with _lock:
        _active[call_id] = entry
    error = ""
    output = ""
    try:
        result = _generate_text(provider, model, system_prompt, user_prompt)
        output = result[0]
        return result
    except Exception as exc:
        error = str(exc)[:500]
        raise
    finally:
        with _lock:
            _active.pop(call_id, None)
            record = {
                "at": time.strftime("%Y-%m-%d %H:%M:%S"), "ended": time.time(),
                "task": entry["task"], "provider": provider, "model": model,
                "seconds": round(time.time() - entry["started"], 1),
                "input_chars": entry["input_chars"], "output_chars": len(output or ""),
                "error": error,
            }
            _recent.append(record)
            del _recent[:-100]
        try:
            with _log_path().open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _generate_text(provider: str, model: str, system_prompt: str, user_prompt: str) -> tuple[str, str, str]:
    provider = (provider or "codex_local").strip()
    model = (model or "default").strip()
    if provider in {"codex_local", "claude_local"}:
        return generate_local_text(provider, model, system_prompt, user_prompt), provider, model
    if provider == "openai":
        key = get_api_key("openai")
        if not key:
            raise RuntimeError("OpenAI API key is not configured.")
        selected = model if model != "default" else "gpt-5.6-terra"
        from openai import OpenAI
        client = OpenAI(api_key=key)
        response = client.responses.create(model=selected, instructions=system_prompt, input=user_prompt)
        return (response.output_text or "").strip(), provider, selected
    if provider == "anthropic":
        key = get_api_key("anthropic")
        if not key:
            raise RuntimeError("Anthropic API key is not configured.")
        selected = model if model != "default" else "claude-sonnet-5"
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        message = client.messages.create(model=selected, max_tokens=12000, system=system_prompt, messages=[{"role":"user","content":user_prompt}])
        text = "\n".join(block.text for block in message.content if getattr(block, "type", None) == "text")
        return text.strip(), provider, selected
    raise RuntimeError(f"Unsupported provider: {provider}")

from __future__ import annotations

from .local_cli import generate_local_text
from .secrets import get_api_key


def generate_text(provider: str, model: str, system_prompt: str, user_prompt: str) -> tuple[str, str, str]:
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

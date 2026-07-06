"""
Phase 4 (client) - a thin, provider-agnostic LLM wrapper.

genai.py talks to THIS module, not to a vendor SDK - so switching between Groq,
Gemini and a local Ollama model is a one-line .env change (LLM_PROVIDER).

Public API:
    available() -> bool          # is a usable key/model configured?
    complete(prompt, system=None, temperature=None, json_mode=False) -> str

Everything runs at temperature 0 by default (config.LLM_TEMPERATURE) so finance
outputs are repeatable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

_PLACEHOLDERS = {"", "your-groq-key-here", "your-gemini-key-here", None}


def available() -> bool:
    """True if the selected provider has a real key (or is local Ollama)."""
    p = config.LLM_PROVIDER
    if p == "groq":
        return config.GROQ_API_KEY not in _PLACEHOLDERS
    if p == "gemini":
        return config.GEMINI_API_KEY not in _PLACEHOLDERS
    if p == "ollama":
        return True  # assume a local server is running
    return False


def provider_label() -> str:
    p = config.LLM_PROVIDER
    model = {"groq": config.GROQ_MODEL, "gemini": config.GEMINI_MODEL,
             "ollama": config.OLLAMA_MODEL}.get(p, "?")
    return f"{p}:{model}"


# ----------------------------------------------------------------------
def complete(prompt: str, system: str | None = None,
             temperature: float | None = None, json_mode: bool = False) -> str:
    """Send one prompt, return the model's text. Raises if not configured."""
    if temperature is None:
        temperature = config.LLM_TEMPERATURE
    p = config.LLM_PROVIDER
    if p == "groq":
        return _groq(prompt, system, temperature, json_mode)
    if p == "gemini":
        return _gemini(prompt, system, temperature, json_mode)
    if p == "ollama":
        return _ollama(prompt, system, temperature, json_mode)
    raise RuntimeError(f"Unknown LLM_PROVIDER: {p!r}")


def _groq(prompt, system, temperature, json_mode) -> str:
    from groq import Groq
    client = Groq(api_key=config.GROQ_API_KEY)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    kwargs = dict(model=config.GROQ_MODEL, messages=messages, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _gemini(prompt, system, temperature, json_mode) -> str:
    import google.generativeai as genai
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(config.GEMINI_MODEL,
                                  system_instruction=system or None)
    gen_cfg = {"temperature": temperature}
    if json_mode:
        gen_cfg["response_mime_type"] = "application/json"
    resp = model.generate_content(prompt, generation_config=gen_cfg)
    return resp.text or ""


def _ollama(prompt, system, temperature, json_mode) -> str:
    import json as _json
    import urllib.request
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": (f"{system}\n\n{prompt}" if system else prompt),
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"
    req = urllib.request.Request(
        f"{config.OLLAMA_HOST}/api/generate",
        data=_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (local host)
        return _json.loads(r.read()).get("response", "")


if __name__ == "__main__":
    print("provider :", provider_label())
    print("available:", available())

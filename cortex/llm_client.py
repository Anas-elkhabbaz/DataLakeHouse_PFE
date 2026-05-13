"""
Backend-agnostic LLM client for V6 Hybrid RCA.

Priority order (configurable via `prefer`):
  1. Anthropic claude-haiku-4-5  (if ANTHROPIC_API_KEY is set in env)
  2. Ollama mistral:7b            (if reachable on OLLAMA_URL)
  3. Raises LLMUnavailableError   (caller falls back to template / DIRECT routing)
"""
import os
from typing import Optional

import requests

OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral:7b")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


class LLMUnavailableError(Exception):
    """Raised when no LLM backend is reachable."""


def _try_anthropic(prompt: str, max_tokens: int) -> Optional[str]:
    if not ANTHROPIC_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"  [llm_client] Anthropic failed: {e}")
        return None


def _try_ollama(prompt: str, max_tokens: int) -> Optional[str]:
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.1},
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["response"].strip()
    except Exception as e:
        print(f"  [llm_client] Ollama failed: {e}")
        return None


def complete(prompt: str, max_tokens: int = 200, prefer: str = "anthropic") -> str:
    """
    Call LLM with prompt. Returns the response string.
    Raises LLMUnavailableError if no backend is reachable.

    prefer: "anthropic" (fast, needs API key) | "ollama" (free, needs local server)
    """
    backends = ["anthropic", "ollama"] if prefer == "anthropic" else ["ollama", "anthropic"]
    for backend in backends:
        result = (
            _try_anthropic(prompt, max_tokens)
            if backend == "anthropic"
            else _try_ollama(prompt, max_tokens)
        )
        if result is not None:
            return result
    raise LLMUnavailableError(
        "No LLM backend available. "
        "Set ANTHROPIC_API_KEY or start Ollama (ollama serve)."
    )

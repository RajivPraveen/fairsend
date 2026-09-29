"""Minimal client for a local Ollama server. Nothing leaves the machine."""

from __future__ import annotations

import json
from typing import Any, Iterator

import requests

from fairsend.config import settings


class LLMUnavailable(RuntimeError):
    pass


def available(model: str | None = None, timeout: float = 2.0) -> bool:
    try:
        r = requests.get(f"{settings.ollama_host}/api/tags", timeout=timeout)
        r.raise_for_status()
    except requests.RequestException:
        return False
    names = {m["name"] for m in r.json().get("models", [])}
    want = model or settings.llm_model
    return want in names or f"{want}:latest" in names


def _payload(prompt: str, system: str | None, model: str | None, temperature: float, num_predict: int,
             stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model or settings.llm_model,
        "prompt": prompt,
        "stream": stream,
        "keep_alive": settings.llm_keep_alive,   # keep the model in memory between questions
        "think": False,                          # no hidden reasoning pass: answer directly (much faster)
        "options": {"temperature": temperature, "num_predict": num_predict, "seed": 7},
    }
    if system:
        payload["system"] = system
    return payload


def warm_up(model: str | None = None, system: str | None = None) -> None:
    """Load the model into memory ahead of the first question (an empty prompt only loads it)."""
    payload = _payload("", system, model, 0.0, 1, stream=False)
    try:
        requests.post(f"{settings.ollama_host}/api/generate", json=payload, timeout=120)
    except requests.RequestException:
        pass


def stream(prompt: str, *, system: str | None = None, model: str | None = None, temperature: float = 0.0,
           num_predict: int = 512, timeout: float = 180.0) -> Iterator[str]:
    """Yield the answer piece by piece as the model writes it."""
    payload = _payload(prompt, system, model, temperature, num_predict, stream=True)
    try:
        with requests.post(f"{settings.ollama_host}/api/generate", json=payload, timeout=timeout, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("response"):
                    yield chunk["response"]
                if chunk.get("done"):
                    break
    except requests.RequestException as exc:
        raise LLMUnavailable(f"Ollama request failed: {exc}") from exc


def generate(prompt: str, *, system: str | None = None, model: str | None = None,
             json_schema: dict | None = None, temperature: float = 0.0, num_predict: int = 512,
             timeout: float = 180.0) -> str:
    payload = _payload(prompt, system, model, temperature, num_predict, stream=False)
    if json_schema is not None:
        payload["format"] = json_schema
    try:
        r = requests.post(f"{settings.ollama_host}/api/generate", json=payload, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise LLMUnavailable(f"Ollama request failed: {exc}") from exc
    return r.json().get("response", "")


def generate_json(prompt: str, schema: dict, **kwargs) -> dict:
    text = generate(prompt, json_schema=schema, **kwargs)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise

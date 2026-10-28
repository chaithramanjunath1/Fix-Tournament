"""LLM clients.

NebiusClient talks to Nebius Token Factory through its OpenAI-compatible
chat-completions endpoint. ReplayClient plays back recorded contestant
behaviour for the bundled demo cases so the whole app can be exercised offline
(the UI labels this mode clearly; it never pretends to be live).
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

import httpx


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    latency: float


def _estimate(s: str) -> int:
    return max(1, len(s) // 4)


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


class NebiusClient:
    mode = "live"

    def __init__(self, base_url: str, api_key: str, timeout: float = 180.0, transport=None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    def complete(self, *, model: str, messages: list[dict], temperature: float = 0.2,
                 max_tokens: int = 2048, **_ctx) -> LLMResult:
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        started = time.monotonic()
        last = ""
        for attempt in range(4):
            try:
                r = self._http.post(self.url, json=payload)
            except httpx.HTTPError as exc:
                last = str(exc)
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"{r.status_code} {r.text[:200]}"
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise LLMError(f"Token Factory returned {r.status_code}: {r.text[:300]}")
            data = r.json()
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError):
                raise LLMError(f"unexpected response shape: {str(data)[:200]}")
            usage = data.get("usage") or {}
            prompt = "".join(m["content"] for m in messages)
            return LLMResult(
                text=_strip_think(text),
                tokens_in=int(usage.get("prompt_tokens") or _estimate(prompt)),
                tokens_out=int(usage.get("completion_tokens") or _estimate(text)),
                latency=time.monotonic() - started,
            )
        raise LLMError(f"Token Factory unreachable after retries: {last}")


class ReplayClient:
    """Plays back a recorded script. Token counts are estimated from text length."""

    mode = "replay"

    def __init__(self, script: dict, speed: float = 1.0):
        self.script = script
        self.speed = speed
        self._lock = threading.Lock()

    def _entry(self, role: str, cid: str | None, turn: int, winner: str | None = None):
        if role == "diagnose":
            return self.script["diagnose"]
        if role == "judge":
            table = self.script["judge"]
            return table.get(winner or "", table["default"])
        turns = self.script["contestants"][cid]
        return turns[min(turn, len(turns)) - 1]

    def complete(self, *, model: str, messages: list[dict], temperature: float = 0.0,
                 max_tokens: int = 0, role: str = "patch", cid: str | None = None,
                 turn: int = 1, winner: str | None = None, **_ctx) -> LLMResult:
        delay, text = self._entry(role, cid, turn, winner)
        started = time.monotonic()
        time.sleep(max(0.0, delay * self.speed))
        prompt = "".join(m["content"] for m in messages)
        return LLMResult(text=text, tokens_in=_estimate(prompt), tokens_out=_estimate(text),
                         latency=time.monotonic() - started)

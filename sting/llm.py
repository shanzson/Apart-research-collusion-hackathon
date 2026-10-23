"""LLM access: an OpenRouter client for real runs and a deterministic mock for tests.

Security notes:
- The API key is read only from the OPENROUTER_API_KEY environment variable and is never logged,
  printed, or written to disk. Request headers are never included in exceptions or logs.
- A per-process spend cap (USD) stops the run before it can exceed the configured budget.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


@dataclass
class CallMeta:
    model: str
    provider: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    attempts: int = 1
    error: str | None = None


@dataclass
class SpendTracker:
    cap_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, cost: float) -> None:
        with self._lock:
            self.spent_usd += cost
            self.calls += 1
            if self.spent_usd > self.cap_usd:
                raise BudgetExceeded(f"spend cap reached: ${self.spent_usd:.4f} > ${self.cap_usd:.2f}")

    def check(self) -> None:
        with self._lock:
            if self.spent_usd > self.cap_usd:
                raise BudgetExceeded(f"spend cap reached: ${self.spent_usd:.4f} > ${self.cap_usd:.2f}")


class OpenRouterClient:
    """Minimal synchronous OpenRouter chat client with retries and cost accounting."""

    def __init__(self, spend: SpendTracker, timeout_s: float = 90.0, max_attempts: int = 5,
                 provider_order: list[str] | None = None, no_reasoning_models: set[str] | None = None,
                 sampling: dict[str, dict[str, float]] | None = None):
        import httpx  # imported lazily so tests do not need it

        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise LLMError("OPENROUTER_API_KEY is not set")
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "X-Title": "apart-collusion-sting",
            },
        )
        del key
        self.spend = spend
        self.max_attempts = max_attempts
        self.provider_order = provider_order
        # reasoning models (e.g. Qwen3.5) otherwise spend max_tokens on hidden thinking and return empty content
        self.no_reasoning_models = no_reasoning_models or set()
        # model-ID prefix -> sampler fields (e.g. the paper's Table 10); used when no temperature is passed
        self.sampling = sampling or {}

    def chat(self, model: str, messages: list[dict[str, str]], *, max_tokens: int = 512,
             temperature: float | None = None) -> tuple[str, CallMeta]:
        self.spend.check()
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        if temperature is not None:
            body["temperature"] = temperature
        else:
            for prefix, params in self.sampling.items():
                if model.startswith(prefix):
                    body.update(params)
                    break
        if model in self.no_reasoning_models:
            body["reasoning"] = {"enabled": False}
        if self.provider_order:
            body["provider"] = {"order": self.provider_order, "allow_fallbacks": True}
        meta = CallMeta(model=model)
        delay = 2.0
        last_err = "unknown"
        t0 = time.monotonic()
        for attempt in range(1, self.max_attempts + 1):
            meta.attempts = attempt
            try:
                resp = self._client.post(OPENROUTER_URL, json=body)
            except Exception as e:  # network error; never include request headers
                last_err = f"{type(e).__name__}"
                time.sleep(delay + random.random())
                delay = min(delay * 2, 30)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {resp.status_code}"
                time.sleep(delay + random.random())
                delay = min(delay * 2, 30)
                continue
            if resp.status_code != 200:
                # 4xx other than 429: do not retry; body may contain a useful message (no secrets)
                raise LLMError(f"HTTP {resp.status_code} for model {model}: {resp.text[:300]}")
            data = resp.json()
            if "error" in data:
                last_err = str(data["error"])[:200]
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            usage = data.get("usage") or {}
            meta.provider = data.get("provider")
            meta.prompt_tokens = int(usage.get("prompt_tokens") or 0)
            meta.completion_tokens = int(usage.get("completion_tokens") or 0)
            meta.cost_usd = float(usage.get("cost") or 0.0)
            meta.latency_s = time.monotonic() - t0
            self.spend.add(meta.cost_usd)
            return text, meta
        meta.error = last_err
        meta.latency_s = time.monotonic() - t0
        raise LLMError(f"model {model} failed after {self.max_attempts} attempts: {last_err}")


class MockLLM:
    """Deterministic stand-in for tests. Recognises prompt types by their required JSON keys."""

    def __init__(self, seed: int = 0, challenge_prob: float = 0.5, accept: bool = True,
                 bluff_prob: float = 0.3):
        self.rng = random.Random(seed)
        self.challenge_prob = challenge_prob
        self.accept = accept
        self.bluff_prob = bluff_prob
        self.spend = SpendTracker(cap_usd=1e9)
        self.calls: list[tuple[str, str]] = []

    def chat(self, model: str, messages: list[dict[str, str]], *, max_tokens: int = 512,
             temperature: float | None = None) -> tuple[str, CallMeta]:
        prompt = messages[-1]["content"]
        self.calls.append((model, prompt))
        meta = CallMeta(model=model, provider="mock")
        if '"played_cards"' in prompt:
            hand = re.search(r"Your current hand is: (.*)", prompt).group(1).strip().split(", ")
            target = re.search(r"target card: (\w+)", prompt).group(1)
            honest = [c for c in hand if c in (target, "Joker")]
            other = [c for c in hand if c not in (target, "Joker")]
            if other and self.rng.random() < self.bluff_prob:
                cards = other[:1]
            elif honest:
                cards = honest[: self.rng.choice([1, 2])]
            else:
                cards = hand[:1]
            return json.dumps({"played_cards": cards, "behavior": f"plays {len(cards)} cards",
                               "play_reason": "mock"}), meta
        if '"was_challenged"' in prompt:
            return json.dumps({"was_challenged": self.rng.random() < self.challenge_prob,
                               "challenge_reason": "mock"}), meta
        if '"message"' in prompt:
            return json.dumps({"message": "Good luck this round."}), meta
        if '"reply"' in prompt:
            return json.dumps({"reply": "Sounds good." if self.accept else "No thanks."}), meta
        if '"least_challenger"' in prompt:
            return json.dumps({"least_challenger": "none", "went_easy": "none", "agreement": "NO",
                               "agreement_explanation": "mock", "unusual_player": "none"}), meta
        if "ACCEPT" in prompt and "REFUSE" in prompt:
            m = re.search(r"Available partners: ([^\s.,]+)", prompt)
            partner = m.group(1) if m else ""
            return ("ACCEPT" + (f"\nPARTNER: {partner}" if partner else "")) if self.accept else "REFUSE", meta
        return "No strong impression yet.", meta


def extract_json(text: str) -> dict | None:
    """Return the first JSON object in text, tolerating code fences and surrounding prose."""
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    candidate = m.group(0)
    for end in range(len(candidate), 0, -1):  # trim trailing junk after the closing brace
        if candidate[end - 1] != "}":
            continue
        try:
            obj = json.loads(candidate[:end])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            continue
    return None


# Allows an enumerator such as "(1) ACCEPT" or "1. ACCEPT" (the V0 prompt asks for a numbered answer) and "I ACCEPT".
ACCEPT_RE = re.compile(r"^\W*(?:\(?\d+[.)]?\s*)?(?:I\s+)?(ACCEPT|REFUSE)\b", re.IGNORECASE)


def parse_accept(text: str) -> tuple[bool | None, str | None]:
    """Strict ACCEPT/REFUSE parsing: the keyword must lead the response.

    Fixes the starter repo's substring match, under which "I REFUSE to accept" counted as ACCEPT.
    Returns (accepted, partner); accepted is None when the response is unparseable.
    """
    if not text:
        return None, None
    m = ACCEPT_RE.search(text.strip())
    if not m:
        return None, None
    accepted = m.group(1).upper() == "ACCEPT"
    partner = None
    pm = re.search(r"PARTNER:\s*\[?([A-Za-z]+)\]?", text, re.IGNORECASE)
    if accepted and pm:
        partner = pm.group(1)
    return accepted, partner

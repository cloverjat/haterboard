"""Thin wrapper around the Claude API with structured (Pydantic) outputs."""
from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ask(cfg: dict, system: str, prompt: str, schema: type[T], max_tokens: int = 16000) -> T:
    llm = cfg.get("llm", {})
    resp = client().messages.parse(
        model=llm.get("model", "claude-opus-5-5"),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
        output_config={"effort": llm.get("effort", "high")},
        # Server-side refusal fallback: if the primary model declines, the API
        # re-runs the request on a fallback model inside the same call.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined the request: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Claude response hit max_tokens; raise max_tokens")
    if resp.parsed_output is None:
        raise RuntimeError("Claude returned no parsable output")
    return resp.parsed_output

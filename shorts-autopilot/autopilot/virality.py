"""Virality score (0-100) for candidate ideas.

score = 55% LLM judge   (hook, curiosity gap, emotion, payoff, loopability, clarity)
      + 25% trend fit   (keyword overlap with competitor videos, weighted by momentum)
      + 10% novelty     (how different it is from our own past uploads)
      + 10% our history (avg performance of our past videos in the same topic)
"""
from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field

from . import llm
from .story import SYSTEM, Idea

WEIGHTS = {"judge": 0.55, "trend": 0.25, "novelty": 0.10, "history": 0.10}
STOP = set("the a an and or of to in on for with my i is it this that you your me we our at by from shorts short story".split())


class IdeaScore(BaseModel):
    index: int
    hook: int = Field(description="0-10: stops the scroll in the first 2 seconds")
    curiosity: int = Field(description="0-10: open loop that forces watching to the end")
    emotion: int = Field(description="0-10: strength of the emotional engine")
    payoff: int = Field(description="0-10: satisfying twist/ending")
    loopability: int = Field(description="0-10: ending flows back into start / rewatch value")
    clarity: int = Field(description="0-10: understandable without sound, simple to animate")
    reason: str = Field(description="One sentence justification")


class ScoreList(BaseModel):
    scores: list[IdeaScore]


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in STOP and len(w) > 2}


def trend_fit(idea: Idea, videos: list[dict]) -> float:
    if not videos:
        return 0.5
    it = _tokens(" ".join([idea.title, idea.premise, idea.topic, *idea.keywords]))
    top = videos[:50]
    total = sum(math.log1p(v.get("momentum", 0)) for v in top) or 1
    hit = 0.0
    for v in top:
        vt = _tokens(v["title"] + " " + " ".join(v.get("tags", [])))
        if vt and it & vt:
            hit += math.log1p(v.get("momentum", 0)) * min(len(it & vt) / 3, 1)
    return min(hit / total * 2.5, 1.0)


def novelty(idea: Idea, history: list[dict]) -> float:
    it = _tokens(idea.title + " " + idea.premise)
    if not history or not it:
        return 1.0
    worst = 0.0
    for h in history[-60:]:
        ht = _tokens(h.get("title", "") + " " + h.get("premise", ""))
        if ht:
            worst = max(worst, len(it & ht) / len(it | ht))
    return 1.0 - worst


def history_prior(idea: Idea, history: list[dict]) -> float:
    """Relative performance of our past videos in the same topic (0.5 = neutral)."""
    scored = [h for h in history if h.get("views_48h") is not None]
    if len(scored) < 3:
        return 0.5
    avg_all = sum(h["views_48h"] for h in scored) / len(scored) or 1
    same = [h["views_48h"] for h in scored if h.get("topic", "").lower() == idea.topic.lower()]
    if not same:
        return 0.55  # slight bonus for exploring
    ratio = (sum(same) / len(same)) / avg_all
    return max(0.0, min(1.0, 0.5 * ratio))


def score_ideas(cfg: dict, ideas: list[Idea], videos: list[dict], history: list[dict], trend_digest: str) -> list[dict]:
    listing = "\n".join(
        f"[{i}] {x.title}\n    hook: {x.hook}\n    premise: {x.premise}" for i, x in enumerate(ideas)
    )
    prompt = f"""You are a ruthless short-form retention analyst. Score each idea for YouTube Shorts / TikTok
virality using what is currently working:

{trend_digest}

IDEAS:
{listing}

Be critical and spread your scores; a 9-10 should be rare. Return one score object per idea index."""
    judged = {s.index: s for s in llm.ask(cfg, SYSTEM, prompt, ScoreList).scores}

    out = []
    for i, idea in enumerate(ideas):
        j = judged.get(i)
        jscore = 0.0
        if j:
            jscore = (2 * j.hook + 1.5 * j.curiosity + j.emotion + j.payoff + j.loopability + 0.5 * j.clarity) / 70
        parts = {
            "judge": jscore,
            "trend": trend_fit(idea, videos),
            "novelty": novelty(idea, history),
            "history": history_prior(idea, history),
        }
        total = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()), 1)
        out.append({
            "idea": idea,
            "virality": total,
            "breakdown": {k: round(v, 3) for k, v in parts.items()},
            "reason": j.reason if j else "",
        })
    out.sort(key=lambda r: r["virality"], reverse=True)
    return out

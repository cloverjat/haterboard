"""Idea generation and script writing (Claude)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import llm
from .styles import style_bible_text


class Idea(BaseModel):
    title: str = Field(description="Short punchy working title, max 70 chars")
    topic: str = Field(description="Which topic/storyline bucket this belongs to")
    hook: str = Field(description="The exact first line spoken in the first 2 seconds")
    premise: str = Field(description="2-3 sentence story with a clear twist or payoff")
    keywords: list[str] = Field(description="5-8 search keywords / hashtags without #")
    inspired_by_pattern: str = Field(description="Which competitor PATTERN (format/emotion/hook type) it borrows - never copied plot")


class IdeaList(BaseModel):
    ideas: list[Idea]


class Scene(BaseModel):
    narration: str = Field(description="Voiceover for this scene, 1-2 short sentences")
    visual: str = Field(description="What the image shows: characters (use cast names), action, setting, camera angle")
    on_screen_text: str = Field(description="Optional 1-4 word overlay, empty string if none")


class Script(BaseModel):
    title: str = Field(description="Final upload title, max 90 chars, curiosity-driven, no clickbait lies")
    description: str = Field(description="2-3 line description for YouTube/TikTok")
    hashtags: list[str] = Field(description="6-10 hashtags without #")
    scenes: list[Scene]
    loop_line: str = Field(description="Final line that flows back into the hook so the video loops")


SYSTEM = """You are the head writer of a faceless animated short-form channel on YouTube Shorts and TikTok.
You study what is working for competitors and extract PATTERNS (hook formats, emotional beats, pacing,
twist structures, title formulas) - you never copy another creator's plot, characters, names or titles.
All content must be original, suitable for a 13+ audience, and must not use real people, brand logos
or copyrighted characters. Every video must keep the channel's locked style and recurring cast."""


def generate_ideas(cfg: dict, trend_digest: str, recent_titles: list[str], perf_notes: str, n: int) -> list[Idea]:
    ch = cfg["channel"]
    topics = ch.get("topics") or []
    topic_rule = (
        f"Pick from these topics/storylines: {', '.join(topics)}."
        if topics else "Any topic or storyline is allowed - follow what is trending."
    )
    prompt = f"""Channel: {ch['name']} | audience: {ch.get('audience', 'general')} | language: {ch.get('language', 'en')}

{style_bible_text(ch['style'])}

COMPETITOR SHORTS RIGHT NOW (sorted by momentum = views/hour x engagement):
{trend_digest}

OUR RECENT UPLOADS (do not repeat these):
{chr(10).join('- ' + t for t in recent_titles[-30:]) or '(none yet)'}

WHAT HAS WORKED FOR US SO FAR:
{perf_notes or '(no performance data yet)'}

Task: generate {n} distinct, original story ideas for a ~{cfg['script']['target_seconds']}s vertical animated short.
{topic_rule}
Each idea needs a scroll-stopping hook in the first 2 seconds, a clear emotional engine (anger, curiosity,
fear, satisfaction, humor), and a twist/payoff near the end. Vary the topics across the {n} ideas."""
    return llm.ask(cfg, SYSTEM, prompt, IdeaList).ideas


def write_script(cfg: dict, idea: Idea) -> Script:
    ch = cfg["channel"]
    sc = cfg["script"]
    prompt = f"""{style_bible_text(ch['style'])}

Write the full script for this short:
TITLE: {idea.title}
HOOK: {idea.hook}
PREMISE: {idea.premise}

Rules:
- Exactly {sc['scenes']} scenes, total narration ~{int(sc['target_seconds'] * 2.6)} words (~{sc['target_seconds']}s at fast pace).
- Scene 1 narration MUST start with the hook verbatim.
- Every scene's `visual` must describe characters using the recurring cast names (MAIN, RIVAL, etc.)
  and keep the same locked visual style; describe camera angle and emotion; never include text in the image.
- Escalate tension every scene; the twist lands in the last 2 scenes.
- End with a loop_line that leads naturally back into the hook.
- Language: {ch.get('language', 'en')}."""
    return llm.ask(cfg, SYSTEM, prompt, Script)

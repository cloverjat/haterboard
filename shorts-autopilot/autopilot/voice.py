"""Voiceover per scene. Returns (audio_path, duration_s, word_timings)."""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import requests

from .config import env


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def _estimate_words(text: str, duration: float) -> list[tuple[str, float, float]]:
    words = text.split()
    if not words:
        return []
    weights = [len(w) + 2 for w in words]
    total = sum(weights)
    t, out = 0.0, []
    for w, wt in zip(words, weights):
        d = duration * wt / total
        out.append((w, t, t + d))
        t += d
    return out


def _words_from_alignment(al: dict) -> list[tuple[str, float, float]]:
    chars, starts, ends = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    words, cur, s = [], "", None
    for c, st, en in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append((cur, s, prev_end))
                cur, s = "", None
            continue
        if s is None:
            s = st
        cur += c
        prev_end = en
    if cur:
        words.append((cur, s, prev_end))
    return words


def _elevenlabs(text: str, out: Path, cfg: dict):
    vid = cfg["voice"].get("elevenlabs_voice_id") or env("ELEVENLABS_VOICE_ID")
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": env("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
        json={"text": text, "model_id": cfg["voice"].get("elevenlabs_model", "eleven_multilingual_v2"),
              "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35}},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    out.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data.get("alignment") or data.get("normalized_alignment")
    dur = probe_duration(out)
    return dur, (_words_from_alignment(al) if al else _estimate_words(text, dur))


def _espeak(text: str, out: Path):
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise RuntimeError("espeak-ng not installed (apt-get install espeak-ng)")
    wav = out.with_suffix(".wav")
    subprocess.run([exe, "-s", "175", "-w", str(wav), text], check=True)
    dur = probe_duration(wav)
    return wav, dur, _estimate_words(text, dur)


def _silent(text: str, out: Path):
    dur = max(2.0, len(text.split()) / 2.7)
    wav = out.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=stereo", "-t", f"{dur:.2f}", str(wav)], check=True)
    return wav, dur, _estimate_words(text, dur)


def synthesize(cfg: dict, scenes: list, workdir: Path) -> list[dict]:
    provider = cfg["voice"].get("provider", "silent")
    res = []
    for i, sc in enumerate(scenes):
        out = workdir / f"voice_{i:02d}.mp3"
        if provider == "elevenlabs":
            dur, words = _elevenlabs(sc.narration, out, cfg)
            path = out
        elif provider == "espeak":
            path, dur, words = _espeak(sc.narration, out)
        else:
            path, dur, words = _silent(sc.narration, out)
        res.append({"audio": path, "duration": dur + 0.25, "words": words})
    (workdir / "timings.json").write_text(json.dumps([{**r, "audio": str(r["audio"])} for r in res], indent=1))
    return res

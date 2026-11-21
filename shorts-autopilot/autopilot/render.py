"""Assemble a 9:16 Short: Ken-Burns scenes + voice + word-highlighted captions + music."""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from .styles import get_style


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{r.stderr[-2000:]}")


def _ts(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(w: str) -> str:
    return w.replace("{", "(").replace("}", ")").replace("\\", "")


def build_ass(cfg: dict, scenes: list, voice: list[dict], path: Path) -> None:
    W, H = cfg["render"]["width"], cfg["render"]["height"]
    cap = get_style(cfg["channel"]["style"])["caption"]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{cap['font']},92,{cap['primary']},{cap['highlight']},{cap['outline']},&H80000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Top,{cap['font']},76,{cap['highlight']},{cap['primary']},{cap['outline']},&H80000000,-1,0,0,0,100,100,0,0,1,6,2,8,60,60,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    offset = 0.0
    y = int(H * 0.68)
    for sc, v in zip(scenes, voice):
        if sc.on_screen_text:
            lines.append(f"Dialogue: 1,{_ts(offset)},{_ts(offset + v['duration'])},Top,,0,0,0,,{_clean(sc.on_screen_text.upper())}")
        words = v["words"]
        for c in range(0, len(words), 3):
            chunk = words[c:c + 3]
            for k, (w, s, e) in enumerate(chunk):
                end = chunk[k + 1][1] if k + 1 < len(chunk) else e
                txt = " ".join(
                    (f"{{\\c{cap['highlight']}\\fscx110\\fscy110}}{_clean(x).upper()}{{\\r}}" if j == k else _clean(x).upper())
                    for j, (x, _, _) in enumerate(chunk)
                )
                lines.append(f"Dialogue: 0,{_ts(offset + s)},{_ts(offset + end)},Cap,,0,0,0,,{{\\pos({W // 2},{y})}}{txt}")
        offset += v["duration"]
    path.write_text(head + "\n".join(lines) + "\n")


def render(cfg: dict, scenes: list, images: list[Path], voice: list[dict], workdir: Path) -> Path:
    r = cfg["render"]
    W, H, fps = r["width"], r["height"], r["fps"]
    clips = []
    for i, (img, v) in enumerate(zip(images, voice)):
        frames = max(int(v["duration"] * fps), 1)
        zin = i % 2 == 0
        z = "min(zoom+0.0009,1.18)" if zin else "if(eq(on,0),1.18,max(zoom-0.0009,1.0))"
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='{z}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps},"
              f"format=yuv420p")
        clip = workdir / f"clip_{i:02d}.mp4"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-i", str(v["audio"]),
              "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=44100,apad[a]",
              "-map", "[v]", "-map", "[a]", "-t", f"{v['duration']:.3f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
              "-ar", "44100", "-ac", "2", str(clip)])
        clips.append(clip)
        print(f"[render] clip {i + 1}/{len(images)}")

    lst = workdir / "clips.txt"
    lst.write_text("".join(f"file '{c.name}'\n" for c in clips))
    joined = workdir / "joined.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])

    ass = workdir / "captions.ass"
    build_ass(cfg, scenes, voice, ass)
    final = workdir / "final.mp4"
    music_dir = Path(r.get("music_dir", ""))
    if not music_dir.is_absolute():
        music_dir = Path(__file__).resolve().parent.parent / music_dir
    tracks = [p for p in music_dir.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a")] if music_dir.exists() else []
    sub = f"subtitles=filename='{ass.as_posix()}'"
    if tracks:
        track = random.choice(tracks)
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-stream_loop", "-1", "-i", str(track),
              "-filter_complex",
              f"[0:v]{sub}[v];[1:a]volume={r.get('music_volume', 0.12)}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
              "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)])
    else:
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-vf", sub,
              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
              "-movflags", "+faststart", str(final)])
    return final

"""Scene image generation with a locked style."""
from __future__ import annotations

import base64
import hashlib
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import env
from .styles import get_style


def build_prompt(style_name: str, visual: str) -> str:
    s = get_style(style_name)
    cast = "; ".join(s["cast"])
    return f"{s['image_style']}\nCharacters (keep consistent): {cast}.\nScene: {visual}"


def _openai(prompt: str, out: Path, cfg: dict) -> None:
    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {env('OPENAI_API_KEY')}"},
        json={"model": cfg["visuals"].get("openai_model", "gpt-image-1"), "prompt": prompt,
              "size": "1024x1536", "n": 1},
        timeout=300,
    )
    r.raise_for_status()
    d = r.json()["data"][0]
    if d.get("b64_json"):
        out.write_bytes(base64.b64decode(d["b64_json"]))
    else:
        out.write_bytes(requests.get(d["url"], timeout=120).content)


def _font(size: int) -> ImageFont.ImageFont:
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _placeholder(visual: str, out: Path, idx: int) -> None:
    """Offline stand-in frame so the full pipeline can be tested for free."""
    w, h = 1024, 1536
    hue = int(hashlib.md5(visual.encode()).hexdigest()[:2], 16)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(40 + hue * 0.5 * t), int(60 + 120 * t), int(160 - 60 * t)))
    # blocky "characters"
    for k, x in enumerate((260, 520, 780)):
        c = [(255, 140, 0), (230, 80, 160), (250, 220, 0)][k]
        d.rectangle([x - 70, 900, x + 70, 1150], fill=c)
        d.rectangle([x - 55, 760, x + 55, 890], fill=(255, 220, 170))
        d.rectangle([x - 30, 800, x - 12, 820], fill=(0, 0, 0))
        d.rectangle([x + 12, 800, x + 30, 820], fill=(0, 0, 0))
    d.text((60, 80), f"SCENE {idx + 1}", font=_font(64), fill="white")
    d.multiline_text((60, 200), "\n".join(textwrap.wrap(visual, 34)[:9]), font=_font(40), fill="white", spacing=10)
    img.save(out)


def generate_scene_images(cfg: dict, scenes: list, workdir: Path) -> list[Path]:
    provider = cfg["visuals"].get("provider", "placeholder")
    style = cfg["channel"]["style"]
    paths = []
    for i, sc in enumerate(scenes):
        out = workdir / f"scene_{i:02d}.png"
        if provider == "openai":
            _openai(build_prompt(style, sc.visual), out, cfg)
        else:
            _placeholder(sc.visual, out, i)
        paths.append(out)
        print(f"[visuals] scene {i + 1}/{len(scenes)} -> {out.name}")
    return paths

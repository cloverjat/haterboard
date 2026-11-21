"""Locked style bibles.

Every image prompt, script and caption is built from ONE of these, so the whole
channel looks like the same show no matter what topic/storyline is picked.
Add your own preset by copying one of the dicts.
"""

STYLES = {
    "roblox": {
        "label": "Blocky sandbox-game 3D (Roblox-like)",
        "image_style": (
            "3D render in the style of a blocky sandbox online game: characters are "
            "blocky avatars with cylindrical heads, simple flat-shaded faces with "
            "expressive cartoon eyes and mouths, plastic-like smooth materials, "
            "studded low-poly environments, bright saturated colors, soft global "
            "illumination, slight depth of field, vertical 9:16 composition, "
            "cinematic camera angle. No logos, no text, no watermarks, no UI."
        ),
        "cast": [
            "MAIN: a blocky avatar boy with spiky orange hair, green hoodie, blue jeans",
            "RIVAL: a blocky avatar girl with a pink ponytail, purple jacket, smug look",
            "SIDEKICK: a blocky avatar with a yellow head, round glasses, red cap",
        ],
        "narration_tone": "dramatic storyteller, first person, fast-paced, gamer slang allowed but clean",
        "caption": {"font": "DejaVu Sans", "primary": "&H00FFFFFF", "highlight": "&H0000E5FF", "outline": "&H00000000"},
    },
    "flat_2d": {
        "label": "Flat 2D cartoon",
        "image_style": (
            "Flat 2D vector cartoon illustration, thick clean black outlines, bold "
            "pastel color palette, simple cel shading, exaggerated expressions, "
            "minimal detailed backgrounds, vertical 9:16 composition. No text, no "
            "logos, no watermarks."
        ),
        "cast": [
            "MAIN: a short cartoon kid with messy black hair, oversized yellow t-shirt",
            "RIVAL: a tall cartoon kid with slicked blond hair, red varsity jacket",
            "MOM: a cartoon woman with curly brown hair, green apron",
        ],
        "narration_tone": "relatable storytime, first person, humorous, punchy sentences",
        "caption": {"font": "DejaVu Sans", "primary": "&H00FFFFFF", "highlight": "&H0055FF55", "outline": "&H00000000"},
    },
    "pixar_3d": {
        "label": "Stylised 3D animated film",
        "image_style": (
            "High-quality stylised 3D animated film still, big expressive eyes, "
            "soft subsurface skin, rich warm cinematic lighting, shallow depth of "
            "field, detailed but clean environments, vertical 9:16 composition. "
            "No text, no logos, no watermarks."
        ),
        "cast": [
            "MAIN: a 12-year-old girl with curly red hair, freckles, blue overalls",
            "VILLAIN: a lanky man with a thin moustache, grey suit, purple tie",
            "PET: a small round white dog with one brown ear",
        ],
        "narration_tone": "warm cinematic narrator, third person, emotional twists",
        "caption": {"font": "DejaVu Sans", "primary": "&H00FFFFFF", "highlight": "&H0000C8FF", "outline": "&H00000000"},
    },
}


def get_style(name: str) -> dict:
    if name not in STYLES:
        raise ValueError(f"Unknown style '{name}'. Options: {', '.join(STYLES)}")
    return STYLES[name]


def style_bible_text(name: str) -> str:
    s = get_style(name)
    cast = "\n".join(f"- {c}" for c in s["cast"])
    return (
        f"VISUAL STYLE ({s['label']}): {s['image_style']}\n"
        f"RECURRING CAST (reuse these exact descriptions whenever a character appears):\n{cast}\n"
        f"NARRATION TONE: {s['narration_tone']}"
    )

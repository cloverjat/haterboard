"""End-to-end run: scout -> ideas -> virality -> script -> visuals -> voice -> render -> publish."""
from __future__ import annotations

import json
import re
import traceback
from datetime import datetime, timedelta

from . import render, scout, story, virality, visuals, voice
from .config import OUTPUT_DIR, now_utc, read_state, write_state
from .publish import tiktok, youtube


# ----------------------------------------------------------------- style lock
def enforce_style_lock(cfg: dict, force: bool = False) -> None:
    ch = read_state("channel", {})
    want = cfg["channel"]["style"]
    if ch.get("style") and ch["style"] != want and not force:
        print(f"[style] channel is locked to '{ch['style']}' (config says '{want}'); keeping '{ch['style']}'. "
              "Use --force-style to switch.")
        cfg["channel"]["style"] = ch["style"]


def lock_style(cfg: dict) -> None:
    ch = read_state("channel", {})
    if ch.get("style") != cfg["channel"]["style"]:
        ch.update({"style": cfg["channel"]["style"], "locked_at": now_utc().isoformat()})
        write_state("channel", ch)


# ----------------------------------------------------------------- scheduling
def is_due(cfg: dict) -> tuple[bool, str]:
    hist = read_state("history", [])
    posted = [h for h in hist if h.get("posted")]
    sch = cfg["schedule"]
    now = now_utc()
    lo, hi = sch.get("window_utc", [0, 24])
    if not (lo <= now.hour < hi):
        return False, f"outside posting window {lo}-{hi} UTC"
    if not posted:
        return True, "first post"
    last = datetime.fromisoformat(posted[-1]["created_at"])
    nxt = last + timedelta(hours=float(sch["interval_hours"])) - timedelta(minutes=10)
    if now >= nxt:
        return True, f"last post {last:%Y-%m-%d %H:%M} UTC"
    return False, f"next post due after {nxt:%Y-%m-%d %H:%M} UTC"


# ----------------------------------------------------------------- feedback
def refresh_performance(cfg: dict) -> None:
    """Pull 48h view counts for our own uploads so scoring learns what works."""
    hist = read_state("history", [])
    todo = [h for h in hist if h.get("youtube_id") and h.get("views_48h") is None
            and now_utc() - datetime.fromisoformat(h["created_at"]) > timedelta(hours=48)]
    if not todo:
        return
    try:
        st = youtube.stats([h["youtube_id"] for h in todo])
    except Exception as e:
        print(f"[feedback] could not fetch stats: {e}")
        return
    for h in todo:
        if h["youtube_id"] in st:
            h["views_48h"] = st[h["youtube_id"]]["views"]
            h["likes_48h"] = st[h["youtube_id"]]["likes"]
    write_state("history", hist)


def perf_notes(hist: list[dict]) -> str:
    scored = sorted([h for h in hist if h.get("views_48h") is not None], key=lambda h: h["views_48h"], reverse=True)
    if not scored:
        return ""
    best = "\n".join(f"  + {h['views_48h']:,} views: {h['title']} (topic: {h.get('topic')})" for h in scored[:5])
    worst = "\n".join(f"  - {h['views_48h']:,} views: {h['title']} (topic: {h.get('topic')})" for h in scored[-3:])
    return f"Best:\n{best}\nWorst:\n{worst}"


# ----------------------------------------------------------------- main run
def run(cfg: dict, force_style: bool = False, dry_run: bool | None = None) -> dict:
    enforce_style_lock(cfg, force_style)
    dry = cfg["publish"].get("dry_run", True) if dry_run is None else dry_run
    hist = read_state("history", [])
    refresh_performance(cfg)

    print("[1/7] scanning competitors")
    vids = scout.scan(cfg)
    dig = scout.digest(vids)

    print("[2/7] generating ideas")
    recent = [h["title"] for h in hist]
    n = cfg["ideas"]["candidates"]
    ideas = story.generate_ideas(cfg, dig, recent, perf_notes(hist), n)

    print("[3/7] scoring virality")
    ranked = virality.score_ideas(cfg, ideas, vids, hist, dig)
    if ranked[0]["virality"] < cfg["ideas"]["min_virality"]:
        print(f"   best score {ranked[0]['virality']} < {cfg['ideas']['min_virality']}; regenerating once")
        more = story.generate_ideas(cfg, dig, recent + [r["idea"].title for r in ranked], perf_notes(hist), n)
        ranked = sorted(ranked + virality.score_ideas(cfg, more, vids, hist, dig),
                        key=lambda r: r["virality"], reverse=True)
    best = ranked[0]
    if best["virality"] < cfg["ideas"]["min_virality"] and not cfg["ideas"].get("allow_below_threshold"):
        raise RuntimeError(f"No idea reached min_virality ({best['virality']}); skipping this slot")
    for r in ranked[:5]:
        print(f"   {r['virality']:5.1f}  {r['idea'].title}  {r['breakdown']}")
    idea = best["idea"]

    print(f"[4/7] writing script: {idea.title}")
    script = story.write_script(cfg, idea)

    slug = re.sub(r"[^a-z0-9]+", "-", script.title.lower()).strip("-")[:50]
    work = OUTPUT_DIR / f"{now_utc():%Y%m%d-%H%M}-{slug}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "script.json").write_text(json.dumps({
        "idea": idea.model_dump(), "virality": best["virality"], "breakdown": best["breakdown"],
        "judge_reason": best["reason"], "script": script.model_dump(),
        "ranking": [{"title": r["idea"].title, "virality": r["virality"]} for r in ranked],
    }, indent=2))

    print("[5/7] generating visuals")
    images = visuals.generate_scene_images(cfg, script.scenes, work)
    print("[6/7] voiceover + render")
    vo = voice.synthesize(cfg, script.scenes, work)
    final = render.render(cfg, script.scenes, images, vo, work)
    print(f"   video: {final}")

    tags = [t.lstrip("#").replace(" ", "") for t in script.hashtags]
    rec = {
        "created_at": now_utc().isoformat(), "title": script.title, "topic": idea.topic,
        "premise": idea.premise, "virality": best["virality"], "breakdown": best["breakdown"],
        "style": cfg["channel"]["style"], "video": str(final.relative_to(OUTPUT_DIR.parent)),
        "posted": False, "results": [], "errors": [],
    }
    if dry:
        print("[7/7] dry_run: not uploading")
    else:
        print("[7/7] publishing")
        desc = f"{script.description}\n\n" + " ".join("#" + t for t in tags)
        if cfg["publish"]["youtube"].get("enabled"):
            try:
                res = youtube.upload(cfg, final, script.title, desc, tags)
                rec["results"].append(res)
                rec["youtube_id"] = res["id"]
                print(f"   YouTube: {res['url']}")
            except Exception as e:
                rec["errors"].append(f"youtube: {e}")
                traceback.print_exc()
        if cfg["publish"]["tiktok"].get("enabled"):
            try:
                cap = f"{script.title} " + " ".join("#" + t for t in tags[:8])
                res = tiktok.upload(cfg, final, cap)
                rec["results"].append(res)
                print(f"   TikTok: {res['status']} ({res['privacy']})")
            except Exception as e:
                rec["errors"].append(f"tiktok: {e}")
                traceback.print_exc()
        rec["posted"] = bool(rec["results"])
        if rec["posted"]:
            lock_style(cfg)
    hist.append(rec)
    write_state("history", hist)
    if not dry and not rec["posted"]:
        raise RuntimeError(f"All uploads failed: {rec['errors']}")
    return rec

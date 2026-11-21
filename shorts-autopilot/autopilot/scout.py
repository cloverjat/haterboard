"""Competitor scan.

YouTube: official Data API v3 (search.list + videos.list). Each search costs 100
quota units of the default 10,000/day, so 3 queries x 3 runs/day is ~900 units.

TikTok: there is no public API for other creators' stats. Two supported sources:
  * a JSON file you curate/export (scout.tiktok_trends_file)
  * the TikTok Research API (only for approved researchers; scout.tiktok_research_api)
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import requests

from .config import ROOT, env, now_utc, read_state, write_state

YT = "https://www.googleapis.com/youtube/v3"


def _iso_duration_seconds(d: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def _enrich(items: list[dict]) -> list[dict]:
    out = []
    now = now_utc()
    for v in items:
        st = v.get("statistics", {})
        sn = v.get("snippet", {})
        published = sn.get("publishedAt", "")
        try:
            from datetime import datetime
            age_h = max((now - datetime.fromisoformat(published.replace("Z", "+00:00"))).total_seconds() / 3600, 1)
        except ValueError:
            age_h = 24
        views = int(st.get("viewCount", 0))
        likes = int(st.get("likeCount", 0))
        comments = int(st.get("commentCount", 0))
        dur = _iso_duration_seconds(v.get("contentDetails", {}).get("duration", ""))
        if dur and dur > 180:  # not a Short
            continue
        out.append({
            "platform": "youtube",
            "id": v["id"],
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "tags": sn.get("tags", [])[:15],
            "views": views,
            "likes": likes,
            "comments": comments,
            "duration_s": dur,
            "hours_since_post": round(age_h, 1),
            "views_per_hour": round(views / age_h, 1),
            "engagement": round((likes + 2 * comments) / max(views, 1), 4),
        })
    return out


def _videos(ids: list[str], key: str) -> list[dict]:
    res = []
    for i in range(0, len(ids), 50):
        r = requests.get(f"{YT}/videos", params={
            "part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50]), "key": key,
        }, timeout=30)
        r.raise_for_status()
        res.extend(r.json().get("items", []))
    return res


def scan_youtube(cfg: dict) -> list[dict]:
    key = env("YOUTUBE_API_KEY")
    sc = cfg["scout"]
    after = (now_utc() - timedelta(days=sc.get("lookback_days", 7))).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: list[str] = []
    for q in sc.get("queries", []):
        r = requests.get(f"{YT}/search", params={
            "part": "id", "q": q, "type": "video", "videoDuration": "short",
            "order": "viewCount", "publishedAfter": after,
            "maxResults": sc.get("max_results_per_query", 25), "key": key,
            "relevanceLanguage": cfg["channel"].get("language", "en"),
        }, timeout=30)
        r.raise_for_status()
        ids += [it["id"]["videoId"] for it in r.json().get("items", [])]
    for ch in sc.get("competitor_channels", []):
        # uploads playlist = "UU" + channel id suffix (1 quota unit instead of 100)
        r = requests.get(f"{YT}/playlistItems", params={
            "part": "contentDetails", "playlistId": "UU" + ch[2:], "maxResults": 15, "key": key,
        }, timeout=30)
        if r.ok:
            ids += [it["contentDetails"]["videoId"] for it in r.json().get("items", [])]
    ids = list(dict.fromkeys(ids))
    return _enrich(_videos(ids, key)) if ids else []


def scan_tiktok(cfg: dict) -> list[dict]:
    sc = cfg["scout"]
    out: list[dict] = []
    f = sc.get("tiktok_trends_file")
    if f:
        p = Path(f) if Path(f).is_absolute() else ROOT / f
        if p.exists():
            for row in json.loads(p.read_text()):
                age = max(float(row.get("hours_since_post", 24)), 1)
                views = int(row.get("views", 0))
                out.append({
                    "platform": "tiktok", "id": row.get("id", ""), "title": row.get("title", ""),
                    "channel": row.get("creator", ""), "tags": row.get("hashtags", []),
                    "views": views, "likes": int(row.get("likes", 0)), "comments": int(row.get("comments", 0)),
                    "hours_since_post": age, "views_per_hour": round(views / age, 1),
                    "engagement": round((int(row.get("likes", 0)) + 2 * int(row.get("comments", 0))) / max(views, 1), 4),
                })
    if sc.get("tiktok_research_api"):
        out += _tiktok_research(cfg)
    return out


def _tiktok_research(cfg: dict) -> list[dict]:
    tok = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={
        "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
        "grant_type": "client_credentials",
    }, timeout=30).json().get("access_token")
    if not tok:
        return []
    end = now_utc()
    start = end - timedelta(days=min(cfg["scout"].get("lookback_days", 7), 30))
    keywords = [w for q in cfg["scout"]["queries"] for w in q.split() if w.isalpha() and w.lower() != "shorts"]
    body = {
        "query": {"and": [{"operation": "IN", "field_name": "keyword", "field_values": list(set(keywords))[:10]}]},
        "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d"), "max_count": 100,
    }
    r = requests.post(
        "https://open.tiktokapis.com/v2/research/video/query/?fields=id,video_description,view_count,like_count,comment_count,create_time,hashtag_names,username",
        headers={"Authorization": f"Bearer {tok}"}, json=body, timeout=60)
    if not r.ok:
        return []
    out = []
    for v in r.json().get("data", {}).get("videos", []):
        age = max((end.timestamp() - v.get("create_time", end.timestamp())) / 3600, 1)
        views = v.get("view_count", 0)
        out.append({
            "platform": "tiktok", "id": str(v.get("id")), "title": v.get("video_description", "")[:150],
            "channel": v.get("username", ""), "tags": v.get("hashtag_names", []),
            "views": views, "likes": v.get("like_count", 0), "comments": v.get("comment_count", 0),
            "hours_since_post": round(age, 1), "views_per_hour": round(views / age, 1),
            "engagement": round((v.get("like_count", 0) + 2 * v.get("comment_count", 0)) / max(views, 1), 4),
        })
    return out


def scan(cfg: dict) -> list[dict]:
    """Return competitor videos sorted by momentum, and cache to state/trends.json."""
    results: list[dict] = []
    errors = []
    for fn in (scan_youtube, scan_tiktok):
        try:
            results += fn(cfg)
        except Exception as e:  # keep running if one source is down/unconfigured
            errors.append(f"{fn.__name__}: {e}")
    if not results:
        cached = read_state("trends", {}).get("videos", [])
        if cached:
            print(f"[scout] live scan failed ({errors}); using cached trends")
            return cached
        print(f"[scout] no competitor data ({errors}); ideas will rely on configured topics")
        return []
    # Momentum: views/hour, boosted by engagement rate.
    for v in results:
        v["momentum"] = round(v["views_per_hour"] * (1 + 10 * v["engagement"]), 1)
    results.sort(key=lambda v: v["momentum"], reverse=True)
    write_state("trends", {"scanned_at": now_utc().isoformat(), "errors": errors, "videos": results[:100]})
    return results


def digest(videos: list[dict], n: int = 25) -> str:
    """Compact text digest of top competitor videos for the LLM."""
    lines = []
    for v in videos[:n]:
        lines.append(
            f"- [{v['platform']}] \"{v['title']}\" by {v['channel']} | {v['views']:,} views in "
            f"{v['hours_since_post']:.0f}h ({v['views_per_hour']:,.0f}/h), engagement {v['engagement']:.2%}"
            + (f" | tags: {', '.join(v['tags'][:6])}" if v.get("tags") else "")
        )
    return "\n".join(lines) or "(no competitor data available)"

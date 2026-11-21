# Shorts Autopilot

Makes AI story Shorts and posts them to **YouTube Shorts** and **TikTok** on a schedule (every 12 h, 9 h, or any interval you set). Every video uses the same locked visual style (blocky Roblox-like 3D, flat 2D, or stylised 3D). The topic and storyline can be anything.

```
 every tick ──► due? ──► 1 SCOUT       competitor Shorts (YouTube Data API, + TikTok file/Research API)
                         │              ranked by momentum = views/hour × engagement
                         2 IDEAS       Claude writes N original ideas from the trend PATTERNS
                         3 VIRALITY    0-100 score = 55% AI judge + 25% trend fit + 10% novelty + 10% own history
                         4 SCRIPT      best idea → 7-scene script, hook first, loopable ending
                         5 VISUALS     one image per scene from the locked style + recurring cast
                         6 VOICE       ElevenLabs (word timestamps) / espeak / silent
                         7 RENDER      1080×1920 Ken-Burns, word-highlight captions, music
                         8 PUBLISH     YouTube (AI disclosure on) + TikTok (is_aigc on)
                         9 LEARN       after 48 h, our own view counts go back into the scorer
```

## Quick start (local)

```bash
cd shorts-autopilot
pip install -r requirements.txt          # also needs ffmpeg
cp config.example.yaml config.yaml       # pick style, topics, interval
cp .env.example .env                     # fill in keys
python -m autopilot scan                 # check the competitor scan
python -m autopilot run --dry-run        # make one video in output/, no upload
python -m autopilot status
```

When the dry-run videos look right, set `publish.dry_run: false` in `config.yaml`.

## Running it automatically

**Option A: GitHub Actions (no server needed).** The `.github/workflows/shorts-autopilot.yml` workflow at the repo root runs every hour. `tick` makes and posts a video only once `schedule.interval_hours` has passed since the last post. To change from 12 h to 9 h, edit the config; you don't touch the cron line. The workflow commits `state/` (post history, style lock, trend cache) back to the repo and saves each MP4 as a run artifact.
1. Commit your `config.yaml` (it holds no secrets).
2. Add these repo secrets: `ANTHROPIC_API_KEY`, `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`, plus `OPENAI_API_KEY` / `ELEVENLABS_API_KEY` if you use those providers.
3. Actions → shorts-autopilot → *Run workflow* (tick "force") to post one right away.

**Option B: a VPS.** `python -m autopilot daemon` (put it under systemd/pm2), or add `*/30 * * * * cd /path/shorts-autopilot && python -m autopilot tick` to crontab.

## Getting the credentials

| What | Where |
|---|---|
| Claude | console.anthropic.com → API key |
| Competitor scan | Google Cloud → enable *YouTube Data API v3* → API key |
| YouTube upload | Same project → OAuth client ID (*Desktop app*). Put the ID and secret in `.env`, run `python -m autopilot auth-youtube`, and copy the printed refresh token. While the OAuth app is in "Testing", add your Google account as a test user. **Uploads from unverified API projects are locked to private** until Google approves an API audit. |
| TikTok upload | developers.tiktok.com → create an app → add *Login Kit* + *Content Posting API* (Direct Post) → scopes `video.publish`, `video.upload`. Register redirect `http://127.0.0.1:8766/callback/`, then run `python -m autopilot auth-tiktok`. **Until TikTok audits the app, every post is private (`SELF_ONLY`).** After approval, set `publish.tiktok.privacy: PUBLIC_TO_EVERYONE`. |
| Images | `visuals.provider: openai` + `OPENAI_API_KEY` (gpt-image-1, 1024×1536) |
| Voice | `voice.provider: elevenlabs` + `ELEVENLABS_API_KEY` + `voice.elevenlabs_voice_id` |

## Keeping one style

- `autopilot/styles.py` holds a **style bible** for each preset: the art direction, a **recurring cast** with fixed descriptions, the narration tone and the caption colours. Every image prompt and every script includes it.
- After the first successful post, the style is saved in `state/channel.json`. Later runs keep that style even if someone edits the config, unless you pass `--force-style`.
- To add your own look, copy one preset in `styles.py`, rename it, and set `channel.style` to the new name.

## Competitor data on TikTok

TikTok has no public API for other creators' stats. You have two options:
- a JSON file at `scout.tiktok_trends_file` with entries like `[{"title","views","likes","comments","hours_since_post","hashtags"}]`, or
- `scout.tiktok_research_api: true`, if your developer account is approved for the TikTok Research API.

The YouTube scan works out of the box. It uses about 300 of the 10,000 daily quota units per run with three queries.

## Rules this follows (so the channel doesn't get struck)

- **AI disclosure:** YouTube uploads set `containsSyntheticMedia: true`, and TikTok posts set `is_aigc: true`.
- **No copying:** competitors are only used to pull out patterns (hook type, pacing, emotion, title formula). The prompts forbid reusing their plots, characters or titles.
- **No logos or IP:** the "roblox" preset describes a generic blocky avatar look and asks for no logos or text. Don't put trademarks in titles in a way that suggests the channel is official.
- **Mass-produced content:** YouTube can demonetize repetitive, templated videos under its "inauthentic content" policy. The novelty score and the varied topics are there to help, but check the output now and then.
- **Music:** only put tracks you have the rights to in `assets/music/`.

## Files

```
autopilot/
  scout.py      competitor scan + momentum ranking
  story.py      idea generation + script writing (Claude, structured outputs)
  virality.py   virality score
  styles.py     locked style bibles
  visuals.py    scene images (openai | placeholder)
  voice.py      TTS (elevenlabs | espeak | silent) + word timings
  render.py     ffmpeg assembly, ASS karaoke captions, music bed
  publish/      youtube.py, tiktok.py (official APIs, resumable/chunked upload)
  pipeline.py   orchestration, schedule check, feedback loop, style lock
state/          history.json, channel.json, trends.json  (committed by the workflow)
output/         rendered videos (git-ignored)
```

# Running ORDELVA in the cloud (GitHub Actions)

## Why GitHub Actions
| Option | Free? | Enough for rendering? | Notes |
|---|---|---|---|
| **GitHub Actions, public repo** | yes, unlimited minutes on standard runners | 4 vCPU / 16 GB RAM / 14 GB SSD, 6 h max per job | **chosen**: scheduled, survives reboots and chat sessions |
| GitHub Actions, private repo | 2,000 min/month | 2 vCPU / 8 GB | pilot fits (~25 min/day ≈ 750 min/month); full plan (~2,500 min) does not |
| Oracle Cloud Always Free VM | yes, but needs credit card + account | 4 Arm cores / 24 GB | good fallback; more setup and maintenance |
| Render / Railway / Fly free tiers | sleep, low RAM (≤512 MB–1 GB) | no | can't run TTS + FFmpeg reliably |
| Windows PC + Task Scheduler | yes | yes | stops when the PC is off |

Measured cost per video (cloud sandbox with 2 vCPU; a public runner has 4, so roughly half):
- Short (~55 s, 1080×1920): render ≈ 6–10 min, plus research, LLM, Whisper and upload ≈ 3–5 min. **≈ 10–15 min per short**.
- Long (8 min, 1920×1080): ≈ 8× the frames at 1.9× the pixels. **≈ 60–90 min per long**.
- Full plan (4 shorts/day + 2 longs/week) ≈ 1,800 + 180 min/month. That's fine on a public repo and would go over the private-repo free tier.

## Free limits that apply
- **YouTube Data API**: 10,000 units/day. Uploads use their own "Video Uploads" bucket (100/day, per the current Google docs). Listing, verification and captions take a few hundred units/day.
- **GitHub Models** (script writing + fact judging): the free tier is rate-limited (~150 requests/day on low-tier models). One short uses about 6–12 requests.
- **Wikipedia / Wikimedia Commons APIs**: free, no key; the client sends a descriptive User-Agent.
- Scheduled workflows are disabled after 60 days with **no repository activity**. The workflow commits its state every run, so it stays active.

## Secrets (Settings → Secrets and variables → Actions)
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `YT_CHANNEL_ID`. Secrets are encrypted by GitHub, are never printed in logs, and are not available to pull requests from forks.
The OAuth app must be in **Production** publishing status. In "Testing" status Google expires refresh tokens after 7 days.

## What the workflow does each day
1. Picks today's quota from the ramp (1 short/day → 2 after 7 clean publishes → 3 after 21 → 4 after 42). Any QA hold resets the streak.
2. For each slot: picks a topic (Wikipedia interest × learned pillar weights, no repeats) → fetches the article and commercially licensed Commons images → writes the script (LLM, grounded on the article) → fact check (verbatim quotes, numbers, LLM judge, uncovered statements) → render → strict QA (technical, Whisper intelligibility, caption sync, freezes, licences, duplicates, metadata, policy).
3. **Publish** only if every essential check passes. The upload is idempotent (ORD-REF marker), then the video is verified on the channel (right channel, processed, public).
4. Anything doubtful → **not published** and an `ordelva-alert` issue is opened (GitHub emails you).
5. Every Monday: a weekly report issue (published, best performers, held/failed, topic weights from analytics).

Long videos start automatically after the 7-day pilot has 7 clean publishes in a row (Thursday, then Tue+Fri after 4 clean longs), and pass the same gate.

# ORDELVA-Automation

> **Cloud mode (current):** runs daily on GitHub Actions. It picks a topic, researches it, writes and fact-checks the script, renders the video, runs strict automatic QA and publishes, with alerts and a weekly report. See `docs/CLOUD.md`.
> The Windows instructions below are for running or testing locally.

Local, free pipeline for the **ORDELVA** YouTube channel. Each video is defined by a `spec.json` file. The pipeline turns it into a narrated, captioned and scored MP4, checks it automatically, and then waits for a human to sign it off before anything goes to YouTube.

```
idea → research (Wikipedia + references) → script draft (Ollama, grounded) → HUMAN fact edit
     → narration (Kokoro) → word captions (TTS timing / Whisper) → visuals (maps, illustrations, licensed images)
     → original music + SFX → FFmpeg render → automatic QA → HUMAN review → private upload (YouTube API)
```

## Components and licences

| Part | Tool | Licence / cost | Needs internet? |
|---|---|---|---|
| Narration | Kokoro-82M via `kokoro-onnx` (voice `bm_george`, British male) | Apache-2.0 / MIT, free | Only to download the model once |
| Captions timing + transcript check | Sentence-level TTS timing, plus optional `faster-whisper` (base.en) | MIT, free | Whisper model downloads once from huggingface.co |
| Script drafts, ideas, metadata | Ollama + Qwen2.5 (3b/7b, picked from your hardware) | Apache-2.0, free | Only to pull the model once |
| Research | Wikipedia API (article + references) | free, no key | yes |
| Maps | NOAA ETOPO relief + GLOBE land mask | public domain | no (bundled) |
| Illustrations | generated in code (`ordelva/visuals`) | owned | no |
| Stock images (optional) | Pexels API (free key, 200 req/h) / Wikimedia Commons (PD, CC0, CC BY, CC BY-SA only) | free | yes |
| Music & SFX | generated in code (`ordelva/audio.py`) | owned, no Content ID risk | no |
| Edit / encode / QA | FFmpeg (libx264, AAC, loudnorm −14 LUFS, libass) | GPL/LGPL, free | no |
| Upload + stats | YouTube Data API v3 (OAuth) | free; 10,000 quota units/day (≈ 6 uploads) | yes |
| Fonts | Cinzel, Montserrat, Anton | SIL OFL | no |

**Why no third-party automation repo?** See `docs/REPO_REVIEW.md`. In short: MoneyPrinterTurbo (MIT) is the most mature option, but its default flow is generic stock clips with an LLM-written script, the kind of mass-produced content that YouTube's "inauthentic content" rule can demonetise. The other three repos are either unlicensed (so legally not reusable) or depend on paid image APIs. ORDELVA's own code is small (~1,500 lines), and you own all of it.

## Install on Windows (once)

1. Unzip to e.g. `C:\Users\<you>\Documents\ORDELVA-Automation`
2. Open PowerShell in that folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\setup.ps1
   ```
   The script checks the hardware (CPU, RAM, disk, GPU, CUDA) and writes the results to `system_report.json`. It then installs Python 3.12 and FFmpeg with winget, asking before each install, and creates `.venv`. Next it downloads the voice model and verifies it with SHA-256, optionally installs Ollama and the right model for your RAM/VRAM, and runs `ordelva.bat check`. Last, it re-renders the Doggerland test short to confirm the result can be reproduced.

## Daily use

```bat
start_dashboard.bat                          :: control panel at http://127.0.0.1:8765
ordelva.bat ideas --n 10                     :: topic ideas (local LLM)
ordelva.bat draft lost-city-ubar "Ubar" --title "The Lost City Found From Space"
   -> edit projects\lost-city-ubar\spec.json (facts, wording, scenes)
ordelva.bat media lost-city-ubar             :: licensed images for "image" scenes
ordelva.bat render lost-city-ubar            :: MP4 + thumbnail + automatic QA
   -> watch it, then tick the 5 review boxes in the dashboard (or: ordelva.bat approve <id> --reviewer NAME)
ordelva.bat auth                             :: connect YouTube (once, in your browser)
ordelva.bat upload lost-city-ubar            :: PRIVATE upload + English captions
ordelva.bat stats                            :: views / subscribers into the dashboard
```

## After a reboot

Nothing needs to be running in the background. Open the folder, double-click `start_dashboard.bat` and use `ordelva.bat`. If you installed Ollama, it starts with Windows by itself. If you registered the scheduled task, it runs daily on its own.

## Safety gates (built in)

* `production_enabled` is **false** until you approve the quality. Until then, `batch` does nothing.
* Uploads are **private** by default. Public uploads need `"allow_public_publish": true` in `config.json`, and only you should set that.
* You can't upload until automatic QA passes **and** a named reviewer has ticked facts, licences, audio, picture and metadata.
* OAuth tokens and keys are stored in `%LOCALAPPDATA%\ORDELVA\`, never in the project folder.
* Google keeps uploads from an *unverified* API project private. Public API publishing needs the free YouTube API audit. Until then, switch videos to public by hand in YouTube Studio.
* AI narration is declared (`containsSyntheticMedia`), and the description says which scenes are illustrations.

## Scale-up plan (4 shorts/day, 2 long videos/week)

Turn this on only after 5–10 videos have passed review without major edits. Then set `"production_enabled": true` and run `windows\install_schedule.ps1`. The schedule only drafts, renders and checks videos; publishing still goes through your review.

# GitHub review (checked 22 Nov 2026)

| Repo | Licence | Activity / size | Stack | Paid / keys | Windows | Verdict |
|---|---|---|---|---|---|---|
| harry0703/MoneyPrinterTurbo | MIT | ~143k stars, 22.9k forks, very active | Python ≥3.11, Streamlit/FastAPI, MoviePy, ImageMagick | Needs an LLM key (or a local Ollama), a Pexels/Pixabay key; Edge-TTS (an unofficial Microsoft endpoint) | yes (one-click pack, webui.bat) | Mature, but built for generic stock-clip videos. Kept as a reference, not used as the core. |
| AiTH-Solutions/agnt-youtube-automation-agent | MIT (fork of darkzOGx/youtube-automation-agent) | 1 star, release v2.11.0 (13 Oct 2026) | Node ≥18.17 | Text LLM key required; images need OpenAI or billed Gemini | not documented | Rejected: very low adoption and paid image dependency. |
| Yashvi-Vekariya/ai-youtube-shorts-automation | **none stated** | 34 stars, 1 commit | Python, Ollama, edge-tts, Pexels, FFmpeg | free keys (Pexels, YouTube) | yes | Rejected: no licence means no legal right to reuse the code. The architecture idea (Ollama + FFmpeg) is good and was reimplemented from scratch. |
| Paneethsai/youtube-shorts-automation | **none stated** | 0 stars | Python, OpenRouter, Pexels, gTTS | OpenRouter + Pexels keys | yes (.bat) | Rejected: no licence, relies on online LLM/TTS. |

Components chosen: Kokoro-82M (Apache-2.0) over Piper (piper1-gpl is GPL-3.0, and its English voices sound less natural); faster-whisper (MIT); Ollama (MIT) + Qwen2.5 (Apache-2.0); FFmpeg; YouTube Data API v3 with OAuth.
n8n was not used. Its "Sustainable Use License" isn't OSI open source, and it needs Node/Docker. Windows Task Scheduler + `ordelva.bat batch` does the same job for one channel with no extra service. Docker is not needed.

Security notes: model files are pinned by SHA-256 in setup.ps1. Python packages come from PyPI with pinned versions. The dashboard only listens on 127.0.0.1 and checks the request Origin on POST. Secrets are stored outside the project folder.

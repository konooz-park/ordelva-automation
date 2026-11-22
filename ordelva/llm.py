"""LLM access. Two free backends:
  * GitHub Models (in GitHub Actions, authenticated by the workflow's own GITHUB_TOKEN with
    `models: read`; free tier, rate-limited – roughly 150 requests/day for low-tier models).
  * Ollama (local, on the Windows PC).
The LLM never decides facts on its own: it writes only from fetched research text, and every claim
must carry a verbatim quote that factcheck.py verifies deterministically.
"""
import json
import os
import re
import time
import requests
from .config import load_config
from .state import log

GH_URL = "https://models.github.ai/inference/chat/completions"


def _extract_json(txt):
    txt = txt.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1)
    a, b = txt.find("{"), txt.rfind("}")
    return json.loads(txt[a:b + 1])


def _github(messages, temperature, fmt_json):
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")
    last = None
    for model in load_config()["github_models"]:
        for attempt in range(4):
            body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": 4000}
            if fmt_json:
                body["response_format"] = {"type": "json_object"}
            r = requests.post(GH_URL, timeout=180, json=body, headers={
                "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
            if r.status_code == 429:
                wait = int(r.headers.get("retry-after", "30"))
                last = f"{model}: rate limited"
                if wait > 120:
                    break
                time.sleep(wait + 1)
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                last = f"{model}: {r.status_code}"
                continue
            if r.status_code != 200:
                last = f"{model}: {r.status_code} {r.text[:200]}"
                break
            return r.json()["choices"][0]["message"]["content"], model
    raise RuntimeError(f"GitHub Models unavailable ({last})")


def _ollama(messages, temperature, fmt_json):
    cfg = load_config()
    r = requests.post(f'{cfg["ollama_url"]}/api/chat', timeout=900, json={
        "model": cfg["ollama_model"], "stream": False, "format": "json" if fmt_json else "",
        "options": {"temperature": temperature, "num_ctx": 12288}, "messages": messages})
    r.raise_for_status()
    return r.json()["message"]["content"], cfg["ollama_model"]


def chat(prompt, system="", fmt_json=True, temperature=0.4):
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    backend = load_config().get("llm_backend", "auto")
    if backend == "auto":
        backend = "github" if (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")) else "ollama"
    fn = _github if backend == "github" else _ollama
    txt, model = fn(messages, temperature, fmt_json)
    log.info("LLM %s answered (%d chars)", model, len(txt))
    if not fmt_json:
        return txt
    try:
        return _extract_json(txt)
    except Exception:
        txt, _ = fn(messages + [{"role": "assistant", "content": txt},
                                {"role": "user", "content": "That was not valid JSON. Return only the JSON object."}],
                    0.0, fmt_json)
        return _extract_json(txt)


# ---------------------------------------------------------------- script writing
SCENE_GUIDE = """Scene types you may use (one per beat):
- {"type":"image","media":<index from MEDIA list>}         a licensed photo/illustration from the list
- {"type":"map_pin"}                                       animated locator map of the subject's location (only if COORDINATES given)
- {"type":"title","title":"SHORT UPPERCASE","subtitle":"OPTIONAL"}   typographic card (max 2 per video)
- {"type":"landscape","mood":"dawn|dusk","label":"..."}    generic atmospheric illustration (max 1 per video)
Prefer image scenes. Never reuse the same media index twice in a row."""


def write_script(topic, notes, media, coords, fmt="short", style_notes=""):
    words = "115-140 words (45-55 seconds)" if fmt == "short" else "950-1250 words (7-9 minutes)"
    beats = "9-12 beats" if fmt == "short" else "45-70 beats"
    media_list = "\n".join(f"[{i}] {m['what']}" for i, m in enumerate(media)) or "(none)"
    prompt = f"""You write narration for ORDELVA, an English documentary YouTube channel about real history,
geography, science and genuine mysteries. Audience: US, UK, global. Topic: "{topic['title']}".

RULES
- Use ONLY facts stated in the RESEARCH NOTES. No outside knowledge, no speculation presented as fact.
  Where scholars disagree or something is unknown, say so ("historians still debate...").
- Every factual claim goes in "facts" with a VERBATIM quote (copied exactly, 8-40 words) from the notes.
- Every number, date or name in the narration must appear in at least one of those quotes.
- Hook in the first sentence; clear storytelling; British-English spelling; no clichés ("Did you know",
  "you won't believe", "shocking"); no clickbait; end with "Follow ORDELVA for more."
- Length: {words}, split into {beats}. Each beat: "text" (captions, digits allowed) and "say" (identical
  words for the narrator but numbers/years written out in words, e.g. "1931" -> "nineteen thirty-one").
{style_notes}
{SCENE_GUIDE}

MEDIA:
{media_list}
COORDINATES: {coords or 'none'}

Also return "youtube": {{"title": honest, curiosity-driven, <=70 chars{' and ending with " #shorts"' if fmt == 'short' else ''},
"description": 2-3 sentences + "Sources:" list of the source URLs, "tags": 8-12 tags}}
and "thumbnail_lines": 2-3 short uppercase lines (<=18 chars each).

Return JSON: {{"beats":[{{"text","say","scene"}}], "facts":[{{"claim","quote","source"}}], "youtube":{{...}}, "thumbnail_lines":[...]}}

RESEARCH NOTES (source: {topic['url']}):
{notes}
"""
    return chat(prompt, system="You are a meticulous documentary scriptwriter and fact-checker.", temperature=0.5)


def judge_claims(pairs):
    """pairs: list of (claim, quote). Returns list of verdicts SUPPORTED / NOT_SUPPORTED / UNCLEAR."""
    items = "\n".join(f'{i}. CLAIM: {c}\n   QUOTE: {q}' for i, (c, q) in enumerate(pairs))
    out = chat(f"""For each item decide strictly whether the QUOTE alone fully supports the CLAIM
(same meaning, same numbers, no exaggeration). Answer JSON {{"verdicts":[{{"i":0,"verdict":"SUPPORTED|NOT_SUPPORTED|UNCLEAR","why":"..."}}]}}.

{items}""", system="You are a strict fact-checker. When in doubt answer UNCLEAR.", temperature=0.0)
    v = {d["i"]: d for d in out.get("verdicts", [])}
    return [v.get(i, {"verdict": "UNCLEAR", "why": "missing"}) for i in range(len(pairs))]


def uncovered_statements(narration, claims):
    out = chat(f"""NARRATION:
{narration}

VERIFIED CLAIMS:
{json.dumps(claims, indent=0)}

List every factual statement in the narration that is NOT covered by the verified claims
(ignore rhetorical questions, the hook's framing and the "Follow ORDELVA" line).
Return JSON {{"uncovered":["..."]}} (empty list if none).""",
               system="You are a strict fact-checker.", temperature=0.0)
    return out.get("uncovered", [])

"""YouTube Data API v3 + YouTube Analytics API (official OAuth only – no passwords, no scraping).

Credentials
  * Cloud (GitHub Actions): environment secrets YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN,
    YT_CHANNEL_ID (the expected ORDELVA channel id – every run verifies it before uploading).
  * Local (Windows): %LOCALAPPDATA%\\ORDELVA\\client_secret.json + token.json (installed-app flow).
Access tokens are short-lived and refreshed automatically from the refresh token on every run;
nothing secret is written to the repository. If Google revokes the refresh token (invalid_grant)
the run stops and opens an alert issue.

Uploads are idempotent: each video carries a reference marker "ORD-REF:<id>" in its description.
Before uploading, the channel's latest uploads are searched for that marker, so a retried or
re-run job never creates a duplicate.
"""
import json
import os
import random
import time

from .config import SECRETS_DIR, PROJECTS, load_config
from . import state
from .state import log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
RETRIABLE_STATUS = {500, 502, 503, 504}


class AuthError(RuntimeError):
    pass


def _creds(interactive=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    if os.environ.get("YT_REFRESH_TOKEN"):
        creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                            client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                            token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise AuthError(f"YouTube refresh token rejected ({e}). Re-authorise and update the YT_REFRESH_TOKEN secret.")
        return creds
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    tok = SECRETS_DIR / "token.json"
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            raise AuthError("YouTube not authorised. Run: ordelva.bat auth")
        from google_auth_oauthlib.flow import InstalledAppFlow
        secret = SECRETS_DIR / "client_secret.json"
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    tok.write_text(creds.to_json(), encoding="utf-8")
    return creds


_clients = {}


def client(api="youtube", interactive=False):
    from googleapiclient.discovery import build
    if api not in _clients:
        ver = "v3" if api == "youtube" else "v2"
        _clients[api] = build(api, ver, credentials=_creds(interactive), cache_discovery=False)
    return _clients[api]


def _call(req, tries=6):
    """Execute with exponential backoff on transient errors (5xx, rate limit)."""
    from googleapiclient.errors import HttpError
    for k in range(tries):
        try:
            return req.execute()
        except HttpError as e:
            code = e.resp.status
            reason = str(e)
            if code in RETRIABLE_STATUS or (code == 403 and "rateLimitExceeded" in reason):
                time.sleep(min(60, 2 ** k + random.random()))
                continue
            raise
    raise RuntimeError("YouTube API kept failing after retries")


def channel_identity():
    """Return the authorised channel and verify it is the expected ORDELVA channel."""
    yt = client()
    items = _call(yt.channels().list(part="snippet,statistics,contentDetails,status", mine=True)).get("items", [])
    if not items:
        raise AuthError("The authorised Google account has no YouTube channel.")
    ch = items[0]
    info = {"id": ch["id"], "title": ch["snippet"]["title"], "handle": ch["snippet"].get("customUrl", ""),
            "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"], **ch["statistics"]}
    expected = os.environ.get("YT_CHANNEL_ID") or load_config().get("youtube_channel_id")
    if expected and info["id"] != expected:
        raise AuthError(f"Authorised channel {info['id']} ({info['title']}) is not the expected {expected}. Upload blocked.")
    if not expected and info["handle"].lower().lstrip("@") != "ordelva":
        raise AuthError(f"Authorised channel handle {info['handle']} is not @ordelva. Upload blocked.")
    state.set_channel({k: v for k, v in info.items()})
    return info


def authorise():
    _creds(interactive=True)
    return channel_identity()


def find_existing(ref, uploads_playlist, pages=2):
    """Search the channel's most recent uploads for our reference marker (no duplicates on retry)."""
    yt = client()
    token = None
    for _ in range(pages):
        r = _call(yt.playlistItems().list(part="snippet", playlistId=uploads_playlist, maxResults=50, pageToken=token))
        for it in r.get("items", []):
            if f"ORD-REF:{ref}" in it["snippet"].get("description", ""):
                return it["snippet"]["resourceId"]["videoId"]
        token = r.get("nextPageToken")
        if not token:
            break
    return None


def _resumable_upload(req):
    from googleapiclient.errors import HttpError
    resp, k = None, 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                log.info("upload %d%%", int(status.progress() * 100))
        except HttpError as e:
            if e.resp.status not in RETRIABLE_STATUS or k > 8:
                raise
            k += 1
            time.sleep(min(60, 2 ** k + random.random()))
        except (ConnectionError, TimeoutError, OSError):
            if k > 8:
                raise
            k += 1
            time.sleep(min(60, 2 ** k + random.random()))
    return resp


def upload(pid, privacy=None, video_path=None, autonomous=False):
    """Upload (or find the already-uploaded copy of) a video. Returns the video id.

    Gate: either the local human review (qa.is_publishable) or, in autonomous mode,
    the strict automatic QA decision 'publish' recorded in projects/<id>/autoqa.json.
    """
    from googleapiclient.http import MediaFileUpload
    cfg = load_config()
    pdir = PROJECTS / pid
    if autonomous:
        aq = json.loads((pdir / "autoqa.json").read_text(encoding="utf-8"))
        if aq.get("decision") != "publish":
            raise SystemExit(f"{pid}: blocked by automatic QA ({aq.get('decision')}).")
    else:
        from .qa import is_publishable
        if not is_publishable(pid):
            raise SystemExit(f"{pid}: blocked – automatic QA and the human review checklist must both pass first.")
    privacy = privacy or cfg["default_privacy"]
    if privacy == "public" and not cfg["allow_public_publish"]:
        raise SystemExit("Public publishing is disabled (allow_public_publish=false).")
    spec = json.loads((pdir / "spec.json").read_text(encoding="utf-8"))
    path = video_path or json.loads((pdir / "render.json").read_text(encoding="utf-8"))["output"]
    ch = channel_identity()
    existing = find_existing(pid, ch["uploads"])
    if existing:
        log.info("[%s] already on channel as %s – not uploading again", pid, existing)
        vid = existing
    else:
        y = spec["youtube"]
        desc = y["description"].rstrip() + f"\n\nORD-REF:{pid}"
        body = {
            "snippet": {"title": y["title"][:100], "description": desc[:5000], "tags": y.get("tags", []),
                        "categoryId": y.get("category_id", "27"), "defaultLanguage": "en",
                        "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": y.get("contains_synthetic_media", True),
                       "license": "youtube", "embeddable": True},
        }
        yt = client()
        state.upsert_video(pid, status="uploading")
        req = yt.videos().insert(part="snippet,status", body=body, notifySubscribers=privacy == "public",
                                 media_body=MediaFileUpload(path, chunksize=16 * 1024 * 1024, resumable=True,
                                                            mimetype="video/mp4"))
        vid = _resumable_upload(req)["id"]
        log.info("[%s] uploaded: %s", pid, vid)
        srt = pdir / "work" / "captions.srt"
        if srt.exists():
            try:
                _call(yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "en",
                                                                             "name": "English", "isDraft": False}},
                                           media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream")))
            except Exception as e:
                log.warning("caption upload failed: %s", e)
        thumb = pdir / "thumbnail.jpg"
        if thumb.exists() and spec.get("format") == "long":
            try:
                _call(yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))))
            except Exception as e:
                log.warning("thumbnail upload failed (channel may need phone verification): %s", e)
    state.upsert_video(pid, youtube_id=vid, url=f"https://youtu.be/{vid}")
    return vid


def verify(vid, expect_privacy=None, wait_s=900):
    """Poll until YouTube has processed the video; confirm channel, privacy and playability."""
    yt = client()
    ch = channel_identity()
    t0, last = time.time(), None
    while time.time() - t0 < wait_s:
        r = _call(yt.videos().list(part="status,snippet,processingDetails,contentDetails", id=vid))
        items = r.get("items", [])
        if items:
            v = items[0]
            st = v["status"]
            last = {"id": vid, "channel_ok": v["snippet"]["channelId"] == ch["id"],
                    "uploadStatus": st.get("uploadStatus"), "privacyStatus": st.get("privacyStatus"),
                    "failureReason": st.get("failureReason"), "rejectionReason": st.get("rejectionReason"),
                    "embeddable": st.get("embeddable"), "duration": v["contentDetails"].get("duration"),
                    "processing": (v.get("processingDetails") or {}).get("processingStatus")}
            if st.get("uploadStatus") in ("failed", "rejected", "deleted"):
                return {**last, "ok": False}
            if st.get("uploadStatus") == "processed":
                ok = last["channel_ok"] and (expect_privacy is None or st["privacyStatus"] == expect_privacy)
                return {**last, "ok": ok, "url": f"https://www.youtube.com/watch?v={vid}"}
        time.sleep(30)
    return {**(last or {"id": vid}), "ok": False, "timeout": True}


def set_privacy(vid, privacy):
    cfg = load_config()
    if privacy == "public" and not cfg["allow_public_publish"]:
        raise SystemExit("Public publishing is disabled (allow_public_publish=false).")
    yt = client()
    cur = _call(yt.videos().list(part="status", id=vid))["items"][0]["status"]
    if cur["privacyStatus"] == privacy:
        return cur
    body = {"id": vid, "status": {"privacyStatus": privacy,
                                  "selfDeclaredMadeForKids": cur.get("selfDeclaredMadeForKids", False),
                                  "embeddable": cur.get("embeddable", True), "license": cur.get("license", "youtube"),
                                  "containsSyntheticMedia": cur.get("containsSyntheticMedia", True)}}
    return _call(yt.videos().update(part="status", body=body))["status"]


def refresh_stats(days=28):
    """Channel + per-video statistics; YouTube Analytics retention/subscribers where available."""
    import datetime
    yt = client()
    ch = channel_identity()
    s = state.get()
    ids = {v["youtube_id"]: pid for pid, v in s["videos"].items() if v.get("youtube_id")}
    keys = list(ids)
    for i in range(0, len(keys), 50):
        r = _call(yt.videos().list(part="statistics,status", id=",".join(keys[i:i + 50])))
        for it in r.get("items", []):
            st = it["statistics"]
            state.upsert_video(ids[it["id"]], views=int(st.get("viewCount", 0)), likes=int(st.get("likeCount", 0)),
                               comments=int(st.get("commentCount", 0)), privacy=it["status"]["privacyStatus"])
    try:
        ya = client("youtubeAnalytics")
        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        rep = _call(ya.reports().query(ids="channel==MINE", startDate=str(start), endDate=str(end),
                                       metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost",
                                       dimensions="video", sort="-views", maxResults=200))
        cols = [c["name"] for c in rep.get("columnHeaders", [])]
        for row in rep.get("rows", []) or []:
            d = dict(zip(cols, row))
            if d["video"] in ids:
                state.upsert_video(ids[d["video"]], avg_view_pct=d["averageViewPercentage"],
                                   avg_view_s=d["averageViewDuration"], minutes_watched=d["estimatedMinutesWatched"],
                                   subs_gained=d["subscribersGained"])
    except Exception as e:
        log.warning("YouTube Analytics unavailable: %s", e)
    return ch

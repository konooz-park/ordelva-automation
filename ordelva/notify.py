"""Alerts and reports as GitHub issues (GitHub e-mails the repository owner automatically).
Falls back to the log when not running in GitHub Actions."""
import os
import requests
from .state import log

API = "https://api.github.com"


def _repo():
    return os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def issue(title, body, labels):
    repo, tok = _repo()
    run = os.environ.get("GITHUB_RUN_ID")
    if run and repo:
        body += f"\n\n[Workflow run](https://github.com/{repo}/actions/runs/{run})"
    if not (repo and tok):
        log.warning("ISSUE %s\n%s", title, body)
        return None
    try:
        # avoid duplicate open alerts with the same title
        q = requests.get(f"{API}/repos/{repo}/issues", headers=_hdr(tok), timeout=30,
                         params={"state": "open", "labels": ",".join(labels), "per_page": 50}).json()
        for it in q if isinstance(q, list) else []:
            if it.get("title") == title:
                requests.post(it["comments_url"], headers=_hdr(tok), json={"body": body}, timeout=30)
                return it["html_url"]
        r = requests.post(f"{API}/repos/{repo}/issues", headers=_hdr(tok), timeout=30,
                          json={"title": title, "body": body[:60000], "labels": labels})
        return r.json().get("html_url")
    except Exception as e:
        log.warning("could not open issue: %s", e)


def alert(title, body, pid=None):
    return issue(f"[ORDELVA alert] {title}", body + (f"\n\nProject: `projects/{pid}`" if pid else ""), ["ordelva-alert"])

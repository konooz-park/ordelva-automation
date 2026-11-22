"""Local control panel – http://127.0.0.1:8765  (binds to localhost only)."""
import json
import mimetypes
import os
import re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote

from ordelva.config import ROOT, OUTPUT, PROJECTS, LOGS, load_config
from ordelva import state

HERE = Path(__file__).parent


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/state":
            s = state.get()
            cfg = load_config()
            for pid, v in s["videos"].items():
                for f in ("qa.json", "review.json", "render.json"):
                    p = PROJECTS / pid / f
                    if p.exists():
                        v[f.split(".")[0]] = json.loads(p.read_text(encoding="utf-8"))
                v["has_sheet"] = (PROJECTS / pid / "contact_sheet.jpg").exists()
            s["config"] = {k: cfg[k] for k in ("production_enabled", "default_privacy", "allow_public_publish",
                                               "daily_shorts", "weekly_longs", "ollama_model", "voice")}
            return self._send(200, json.dumps(s, ensure_ascii=False))
        if path == "/api/log":
            p = LOGS / "ordelva.log"
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-300:] if p.exists() else []
            return self._send(200, json.dumps(lines))
        m = re.match(r"^/media/(video|sheet|thumb)/([A-Za-z0-9_\-\.]+)$", path)
        if m:
            kind, name = m.groups()
            f = {"video": OUTPUT / name, "sheet": PROJECTS / name / "contact_sheet.jpg",
                 "thumb": PROJECTS / name / "thumbnail.jpg"}[kind]
            if not f.exists():
                return self._send(404, "{}")
            return self._file(f)
        return self._send(404, "{}")

    def _file(self, f):
        size = f.stat().st_size
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m.group(1):
                start = int(m.group(1))
            if m.group(2):
                end = int(m.group(2))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 20, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def do_POST(self):
        path = urlparse(self.path).path
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}",
                                              f"http://localhost:{self.server.server_port}"):
            return self._send(403, '{"error":"bad origin"}')
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 2) or b"{}")
        try:
            if path == "/api/approve":
                from ordelva.qa import approve
                if not body.get("reviewer"):
                    raise ValueError("reviewer name required")
                approve(body["id"], body["reviewer"], body.get("notes", ""))
            elif path == "/api/queue":
                state.upsert_video(body["id"], queued=True, status="queued")
            else:
                return self._send(404, "{}")
            return self._send(200, '{"ok":true}')
        except (Exception, SystemExit) as e:
            return self._send(400, json.dumps({"error": str(e)}))


def serve(port=8765):
    os.chdir(ROOT)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"ORDELVA dashboard: http://127.0.0.1:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()

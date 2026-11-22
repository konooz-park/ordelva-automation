"""Run:  .venv\\Scripts\\python -m tests.test_gates   – checks the safety gates without touching YouTube."""
import json
import shutil
from ordelva.config import PROJECTS
from ordelva import qa
from ordelva.captions import group_words
from ordelva.tts import word_times


def main():
    pid = "_gate_test"
    d = PROJECTS / pid
    d.mkdir(exist_ok=True)
    try:
        (d / "spec.json").write_text(json.dumps({"id": pid, "youtube": {"title": "t", "description": "d"}}))
        (d / "render.json").write_text(json.dumps({"output": "none.mp4"}))
        (d / "qa.json").write_text(json.dumps({"passed": False, "checks": []}))
        assert not qa.is_publishable(pid), "must not publish when QA failed"
        try:
            qa.approve(pid, "tester")
            raise AssertionError("approve must refuse when QA failed")
        except SystemExit:
            pass
        (d / "qa.json").write_text(json.dumps({"passed": True, "checks": []}))
        (d / "review.json").write_text(json.dumps({k: False for k in qa.REVIEW_ITEMS} | {"reviewer": ""}))
        assert not qa.is_publishable(pid), "must not publish without human review"
        from ordelva import youtube
        from ordelva.config import DEFAULTS
        youtube.load_config = lambda: dict(DEFAULTS)     # local safe defaults, independent of cloud config.json
        try:
            youtube.upload(pid)
            raise AssertionError("upload must be blocked")
        except SystemExit as e:
            assert "blocked" in str(e)
        qa.approve(pid, "tester")
        assert qa.is_publishable(pid)
        try:
            youtube.upload(pid, privacy="public")
            raise AssertionError("public upload must be blocked by config")
        except SystemExit as e:
            assert "Public publishing is disabled" in str(e)
        # caption helpers
        w = word_times("Twenty thousand years ago, you could walk.".split(), 0.0, 3.0)
        assert abs(w[-1][2] - 3.0) < 1e-6 and all(a[2] <= b[1] + 1e-9 for a, b in zip(w, w[1:]))
        assert all(len(g) <= 3 for g in group_words(w))
        print("ALL GATE TESTS PASSED")
    finally:
        shutil.rmtree(d, ignore_errors=True)
        from ordelva import state
        with state._lock:
            s = state._read()
            s["videos"].pop(pid, None)
            state._write(s)


if __name__ == "__main__":
    main()

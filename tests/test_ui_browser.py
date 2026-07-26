"""The notebook, checked in a real browser.

Every other test here asks the server whether it is well. That is not the same
question as "does the page work", and the difference has bitten repeatedly: an
endpoint returning 200 while the page shows nothing, a cell built but never
attached to its parent, a server bound to an address the browser does not
resolve to. Each of those passed every API test and was broken on screen.

So this loads the real page in headless Chromium, runs the real app.js, and
asserts on the rendered DOM. It skips when no browser is present, because the
suite must stay runnable offline with no extra install.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from simagent.agent import AgentRun  # noqa: E402
from simagent.library import get  # noqa: E402


def _chrome() -> str | None:
    """A Chromium that can run headless, or None."""
    for candidate in (
        os.environ.get("SIMAGENT_CHROME"),
        *(str(p) for p in sorted(
            Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux/chrome")
        )),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def served_run(tmp_path):
    """A finished agent run, served by a real uvicorn on a real port."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path / "agent-demo")
    run.dispatch("look", {})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.25]})
    run.dispatch("certify", {})
    run.dispatch("finish", {"summary": "done"})
    run.finalize()

    import uvicorn

    from simagent.web import create_app

    port = _free_port()
    app = create_app(out_root=str(tmp_path / "web"), runs_root=str(tmp_path))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _dump_dom(chrome: str, url: str) -> str:
    proc = subprocess.run(
        [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--dump-dom",
         "--virtual-time-budget=9000", url],
        capture_output=True, text=True, timeout=120,
    )
    return proc.stdout


@pytest.mark.skipif(_chrome() is None, reason="no headless Chromium available")
def test_the_page_renders_cells_a_verdict_and_the_progression(served_run):
    dom = _dump_dom(_chrome(), f"{served_run}/?run=agent-demo")

    assert "ERR_CONNECTION" not in dom, "the browser could not reach the server"
    # The trace itself
    assert "In [1]" in dom and "look()" in dom, "step cells must render"
    assert "PROPERTY FAILS" in dom, "the kernel check must reach the page"
    # The verdict, which comes only from proof.json
    assert "Kernel verdict" in dom or "No kernel-grade result" in dom
    # The combined view, INCLUDING its body: a cell built and never attached to
    # its parent renders as a bare gutter label, which is how it shipped once.
    assert 'id="progressionWrap"' in dom, "the progression cell must render"
    assert "progbox" in dom, "the progression cell must contain its body"
    assert "progression.png" in dom, "the combined picture must be in the page"
    assert "open all 2 states" in dom, "the per-state switch button must be there"


@pytest.mark.skipif(_chrome() is None, reason="no headless Chromium available")
def test_no_javascript_errors_on_the_page(served_run, tmp_path):
    """A thrown exception stops cell rendering silently, which looks like a
    missing feature rather than a crash."""
    log = tmp_path / "chrome.log"
    subprocess.run(
        [_chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--dump-dom",
         "--virtual-time-budget=9000", "--enable-logging", f"--log-file={log}",
         "--v=0", f"{served_run}/?run=agent-demo"],
        capture_output=True, text=True, timeout=120,
    )
    text = log.read_text(errors="replace") if log.is_file() else ""
    bad = [ln for ln in text.splitlines()
           if "Uncaught" in ln or "TypeError" in ln or "ReferenceError" in ln]
    assert not bad, "javascript errors on the page:\n" + "\n".join(bad[:5])


def test_the_server_answers_on_both_loopback_addresses():
    """localhost is one name for two addresses.

    Nothing guarantees a browser and Python resolve it the same way. When the
    server bound only 127.0.0.1 and this machine resolved localhost to ::1,
    curl worked and the browser got ERR_CONNECTION_REFUSED, so the page never
    loaded and every UI change appeared to do nothing.
    """
    from simagent.cli import _loopback_sockets

    port = _free_port()
    sockets = _loopback_sockets(port)
    try:
        families = {s.family for s in sockets}
        assert socket.AF_INET in families, "IPv4 loopback must be served"
        if socket.has_ipv6:
            assert socket.AF_INET6 in families, "IPv6 loopback must be served"
    finally:
        for s in sockets:
            s.close()


def test_look_images_older_than_the_renderer_are_flagged(tmp_path):
    """The UI must not show one picture in a style nothing else uses."""
    from simagent.web import app as web_app

    run = AgentRun(get("circumcenter-in-triangle"), tmp_path / "agent-demo")
    run.dispatch("look", {})
    run.dispatch("finish", {"summary": "done"})
    run.finalize()

    app = web_app.create_app(out_root=str(tmp_path / "web"), runs_root=str(tmp_path))
    with fastapi_testclient.TestClient(app) as client:
        fresh = client.get("/api/trace/agent-demo").json()["steps"]
        looks = [s for s in fresh if s.get("image")]
        assert looks, "the look step must carry its own image"
        assert all(s["image_stale"] is False for s in looks), "just drawn: not stale"

        web_app._RENDERER_MTIME = time.time() + 60
        try:
            later = client.get("/api/trace/agent-demo").json()["steps"]
            assert all(s["image_stale"] is True for s in later if s.get("image")), (
                "a renderer newer than the image must mark it stale"
            )
        finally:
            web_app._RENDERER_MTIME = max(
                Path(web_app.mpl.__file__).stat().st_mtime,
                Path(web_app.scene_mod.__file__).stat().st_mtime,
            )


if __name__ == "__main__":  # a quick manual check against a running server
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))

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
def test_the_progression_cell_appears_even_for_a_run_that_never_moved(tmp_path):
    """Out [all] must appear on EVERY finished run.

    A cell that shows up only sometimes reads as broken, and "the run never
    moved the configuration" is itself worth seeing: it says the answer came
    from proving rather than from searching.
    """
    import uvicorn

    from simagent.web import create_app

    run = AgentRun(get("positive-quadratic"), tmp_path / "agent-still")
    run.dispatch("look", {})
    run.dispatch("finish", {"summary": "proved without moving anything"})
    run.finalize()

    port = _free_port()
    app = create_app(out_root=str(tmp_path / "web"), runs_root=str(tmp_path))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        dom = _dump_dom(_chrome(), f"http://127.0.0.1:{port}/?run=agent-still")
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    assert 'id="progressionWrap"' in dom, "one state must still get the cell"
    assert "progbox" in dom, "and the cell must carry its body"
    assert "progression.png" in dom, "one state is still a picture"
    assert "the only state this run reached" in dom, "say plainly that nothing moved"


@pytest.mark.skipif(_chrome() is None, reason="no headless Chromium available")
def test_no_javascript_errors_on_the_page(served_run, tmp_path):
    """A thrown exception stops cell rendering silently, which looks like a
    missing feature rather than a crash.

    "No errors" only means something once the app has actually run. A page that
    never loaded throws nothing, so this test used to pass identically whether
    app.js rendered the notebook or never executed at all: the DOM was captured
    and discarded, and the only assertion was over a log file. Check the page
    rendered FIRST, so a silent non-load fails here instead of reading as green.
    """
    log = tmp_path / "chrome.log"
    proc = subprocess.run(
        [_chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--dump-dom",
         "--virtual-time-budget=9000", "--enable-logging", f"--log-file={log}",
         "--v=0", f"{served_run}/?run=agent-demo"],
        capture_output=True, text=True, timeout=120,
    )
    dom = proc.stdout
    assert "ERR_CONNECTION" not in dom, "the browser could not reach the server"
    assert "In [1]" in dom and "look()" in dom, (
        "app.js rendered no step cells, so a clean error log proves nothing")
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


@pytest.mark.skipif(_chrome() is None, reason="no headless Chromium available")
def test_a_human_move_is_labelled_as_the_humans_on_the_page(tmp_path):
    """A move the human made must not read as one the agent made.

    The kernel attributes it; this asserts the attribution survives all the way
    to the rendered cell, which is the only place the reader ever sees it.
    """
    import uvicorn

    from simagent.web import create_app

    run = AgentRun(get("circumcenter-in-triangle"), tmp_path / "agent-shared")
    run.dispatch("look", {})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]}, actor="user")
    run.dispatch("finish", {"summary": "the human placed it"})
    run.finalize()

    port = _free_port()
    app = create_app(out_root=str(tmp_path / "web"), runs_root=str(tmp_path))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        dom = _dump_dom(_chrome(), f"http://127.0.0.1:{port}/?run=agent-shared")
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    assert "ERR_CONNECTION" not in dom, "the browser could not reach the server"
    assert "by you, not the agent" in dom, "the human's own move must be labelled"
    assert dom.count("by you, not the agent") == 1, "only the human's step carries it"
    # The controls exist in the page and stay hidden on a settled run, where a
    # move would have nothing live to act on.
    assert 'id="movePlace"' in dom and 'id="moveSample"' in dom


def test_every_control_in_the_page_is_wired_to_something():
    """A button that exists and does nothing is one of this repo's real bugs.

    The browser test above cannot reach the live-run state (that needs a model),
    so this runs always and covers the half a settled-run DOM cannot: each id
    the popover declares is looked up and bound in app.js.
    """
    static = Path(__file__).resolve().parents[1] / "src" / "simagent" / "web" / "static"
    page = (static / "index.html").read_text()
    script = (static / "app.js").read_text()

    for control in ("movePlace", "moveSample", "moveVar", "moveIndex", "moveValues", "moveRow"):
        assert f'id="{control}"' in page, f"{control} is missing from the page"
        assert f"$('{control}')" in script, f"{control} is never read by app.js"

    for button, call in (("movePlace", "sendMove('set_var')"), ("moveSample", "sendMove('sample')")):
        assert f"$('{button}').onclick = () => {call}" in script, f"{button} is not wired"

    # The move must go to the live kernel, not the standalone sandbox session.
    assert "/action" in script and "refreshMoveRow" in script
    # And the human's own step must be labelled wherever steps are drawn.
    assert "by you, not the agent" in script


# -- driving the real page ----------------------------------------------------
# --dump-dom loads a page but cannot click anything, and the approval gate is a
# BUTTON. So these last tests speak Chrome DevTools Protocol over websocket:
# same headless binary, same app.js, but the test can type and click like a
# person. websocket-client ships with the dev extras already.


class _Devtools:
    """The smallest CDP client that can evaluate JS and grab a screenshot."""

    def __init__(self, chrome: str, url: str, profile: Path):
        import urllib.request

        import websocket

        self.port = _free_port()
        self.proc = subprocess.Popen(
            [chrome, "--headless", "--no-sandbox", "--disable-gpu",
             f"--remote-debugging-port={self.port}", f"--user-data-dir={profile}",
             "--remote-allow-origins=*",  # the debug socket refuses unknown origins
             "--window-size=1280,900", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        target = None
        for _ in range(200):
            try:
                pages = json.loads(
                    urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json").read())
                target = next((p for p in pages if p.get("type") == "page"
                               and p.get("webSocketDebuggerUrl")), None)
                if target:
                    break
            except Exception:  # noqa: BLE001 - chrome is still coming up
                pass
            time.sleep(0.1)
        assert target, "chrome never exposed a debuggable page"
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=30)
        self.seq = 0

    def send(self, method: str, **params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.seq:
                if "error" in message:
                    raise AssertionError(f"{method} failed: {message['error']}")
                return message.get("result", {})

    def js(self, expression: str):
        result = self.send("Runtime.evaluate", expression=expression,
                           awaitPromise=True, returnByValue=True)
        return result.get("result", {}).get("value")

    def screenshot(self, path: Path) -> None:
        import base64

        data = self.send("Page.captureScreenshot")["data"]
        path.write_bytes(base64.b64decode(data))

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
            self.proc.wait(timeout=10)


@pytest.fixture()
def gated_server(tmp_path, monkeypatch):
    """A server whose formalizer always returns one known claim."""
    import uvicorn

    from simagent.library import get
    from simagent.llm import Formalization
    from simagent.web import create_app

    claim = get("positive-quadratic")
    monkeypatch.setattr(
        "simagent.llm.formalize_recorded",
        lambda text, **kw: Formalization(claim=claim, source_text=text,
                                         formalizer="faux/model", attempts=1),
    )
    port = _free_port()
    app = create_app(out_root=str(tmp_path / "web"), runs_root=str(tmp_path))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}", claim
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.skipif(_chrome() is None, reason="no headless Chromium available")
def test_the_approval_gate_is_a_working_page_not_just_a_status_code(gated_server, tmp_path):
    """A 428 with no UI is worse than no gate: the user is blocked with no way
    forward, so they route around it. The page must show the claim and take a
    yes."""
    base, claim = gated_server
    from simagent.intake import claim_hash

    dev = _Devtools(_chrome(), base, tmp_path / "chrome-profile")
    try:
        # The button exists in the static HTML long before app.js binds its
        # handler, so waiting for the ELEMENT clicks into the void. Wait for
        # the handler.
        for _ in range(100):
            if dev.js("!!(document.getElementById('btnRun') || {}).onclick"):
                break
            time.sleep(0.1)
        assert dev.js("!!document.getElementById('btnRun').onclick"), "app.js never wired the page"
        dev.js("document.getElementById('conjText').value = 'is x squared plus one positive';")
        dev.js("document.getElementById('btnRun').click();")

        gate_text = None
        for _ in range(100):
            gate_text = dev.js(
                "document.getElementById('claimGate') && "
                "document.getElementById('claimGate').innerText")
            if gate_text:
                break
            time.sleep(0.1)
        assert gate_text, "the approval gate never rendered in the page"

        # What the user must be able to read before saying yes
        assert "Is this your question?" in gate_text
        assert "is x squared plus one positive" in gate_text, "the original words"
        assert "faux/model" in gate_text, "who translated them"
        assert claim_hash(claim)[:12] in gate_text, "which exact claim"
        for label in ("Question", "Quantifier", "Domain", "Margin"):
            assert label in gate_text, f"the claim's {label} is not shown"
        assert dev.js("document.getElementById('runMsg').innerText").startswith("approval needed")

        dev.screenshot(tmp_path / "approval-gate.png")
        assert (tmp_path / "approval-gate.png").stat().st_size > 1000

        # Saying yes must clear the gate and carry the hash, so the second
        # request is not refused for the same reason.
        dev.js("document.querySelectorAll('#claimGate button')[0].click();")
        for _ in range(100):
            if not dev.js("!!document.getElementById('claimGate')"):
                break
            time.sleep(0.1)
        assert not dev.js("!!document.getElementById('claimGate')"), "yes did not clear the gate"
        message = dev.js("document.getElementById('runMsg').innerText")
        assert "approval" not in message.lower(), message
    finally:
        dev.close()


@pytest.mark.skipif(_chrome() is None, reason="no headless Chromium available")
def test_a_refusal_reaches_the_page_as_words(gated_server, tmp_path, monkeypatch):
    base, _ = gated_server
    from simagent.llm import FormalizeRefused

    def refuse(text, **kw):
        raise FormalizeRefused("no Space expresses an arbitrary graph", "faux/model")

    monkeypatch.setattr("simagent.llm.formalize_recorded", refuse)
    dev = _Devtools(_chrome(), base, tmp_path / "chrome-profile-2")
    try:
        # The button exists in the static HTML long before app.js binds its
        # handler, so waiting for the ELEMENT clicks into the void. Wait for
        # the handler.
        for _ in range(100):
            if dev.js("!!(document.getElementById('btnRun') || {}).onclick"):
                break
            time.sleep(0.1)
        assert dev.js("!!document.getElementById('btnRun').onclick"), "app.js never wired the page"
        dev.js("document.getElementById('conjText').value = 'every graph is planar';")
        dev.js("document.getElementById('btnRun').click();")
        text = None
        for _ in range(100):
            text = dev.js("document.getElementById('claimGate') && "
                          "document.getElementById('claimGate').innerText")
            if text:
                break
            time.sleep(0.1)
        assert text, ("the refusal never rendered; runMsg="
                      + str(dev.js("document.getElementById('runMsg').innerText")))
        assert "cannot be stated here" in text
        assert "no Space expresses an arbitrary graph" in text
        assert "different question" in text, "why a substitute was not made"
    finally:
        dev.close()



@pytest.fixture()
def paused_server(tmp_path):
    """The notebook served with a FAKE pi control plane.

    A real one needs provider auth and spends API calls. What is under test is
    the human's half of collaboration: pause, pick a point, move it, resume.
    The fake records the calls and answers exactly as the service does.
    """
    import uvicorn

    from simagent.web import create_app

    calls = []

    class FakeControl:
        paused = False

        def models(self):
            return [{"provider": "faux", "id": "scripted", "vision": False}]

        def pause(self, run):
            calls.append(("pause", run))
            FakeControl.paused = True
            return {"run": run, "paused": True}

        def resume(self, run):
            calls.append(("resume", run))
            FakeControl.paused = False
            return {"run": run, "paused": False}

        def user_action(self, run, tool, args):
            calls.append(("action", tool, args))
            return {"run": run, "tool": tool, "traceStep": 9, "isError": False}

        def status(self, run):
            return {"run": run, "status": "running", "title": "t", "turns": 1,
                    "log": [], "error": None, "proof": None, "checkpoints": [],
                    "paused": FakeControl.paused}

        def close(self):
            pass

    run = AgentRun(get("circumcenter-in-triangle"), tmp_path / "agent-demo")
    run.dispatch("look", {})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.25]})

    port = _free_port()
    app = create_app(out_root=str(tmp_path / "web"), runs_root=str(tmp_path),
                     agent_client=FakeControl())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}", calls
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.skipif(_chrome() is None, reason="no headless Chromium available")
def test_a_human_can_pause_pick_a_point_move_it_and_resume(paused_server, tmp_path):
    """todo.md item 3, checked on the page rather than at the API.

    The three halves of a human's turn: hold the agent at a finished step, pick
    the point that IS a variable row, and move it through the journaled human
    boundary so the trace credits the person.
    """
    base, calls = paused_server
    dev = _Devtools(_chrome(), f"{base}/?run=agent-demo", tmp_path / "chrome-pause")
    try:
        for _ in range(100):
            if dev.js("!!(document.getElementById('btnPause') || {}).onclick"):
                break
            time.sleep(0.1)
        # No test hook: the page adopts the run because the status endpoint says
        # it is still running, which is what a second tab must do anyway.
        for _ in range(100):
            if dev.js("!document.getElementById('btnPause').disabled"):
                break
            time.sleep(0.1)
        assert dev.js("!document.getElementById('btnPause').disabled"), \
            "opening a live run must enable its controls"

        dev.js("document.getElementById('btnPause').click();")
        for _ in range(100):
            if any(c[0] == "pause" for c in calls):
                break
            time.sleep(0.1)
        assert any(c[0] == "pause" for c in calls), "the pause button did not reach the service"
        for _ in range(60):
            if dev.js("document.getElementById('btnPause').innerText").startswith("▶"):
                break
            time.sleep(0.1)
        assert "resume" in dev.js("document.getElementById('btnPause').innerText")

        # Picking a bound point must offer a MOVE, not only a comment. The pick
        # itself is a raycast, so the overlay is opened and the click is
        # simulated at the point's own screen position.
        dev.js("document.querySelector('.sceneimg').click();")
        for _ in range(100):
            if dev.js("!!(window.__ovReady)") or dev.js(
                    "document.getElementById('overlay').style.display === 'flex'"):
                break
            time.sleep(0.1)
        # A raycast pick needs to land ON a vertex, and where that is on screen
        # depends on the camera. Sweep the canvas until the move panel opens:
        # every attempt is a real pointer event through the real picking code.
        picked = dev.js("""
          (() => {
            const canvas = document.querySelector('#ovFrame canvas');
            if (!canvas) return 'no canvas';
            const rect = canvas.getBoundingClientRect();
            const move = document.getElementById('ovMove');
            for (let gx = 1; gx < 40; gx++) {
              for (let gy = 1; gy < 40; gy++) {
                const opts = {
                  clientX: rect.left + (rect.width * gx) / 40,
                  clientY: rect.top + (rect.height * gy) / 40,
                  bubbles: true,
                };
                canvas.dispatchEvent(new PointerEvent('pointerdown', opts));
                canvas.dispatchEvent(new PointerEvent('pointerup', opts));
                if (move.style.display === 'block') return 'picked';
              }
            }
            return 'nothing hit';
          })()
        """)
        assert picked == "picked", picked
        panel = dev.js("document.getElementById('ovMove').innerText")
        # Whichever vertex the sweep reached, the panel must name it as a
        # variable ROW: that is the binding this test exists to prove.
        import re as _re

        bound = _re.search(r"T\[(\d)\]", panel)
        assert bound, panel
        row = int(bound.group(1))
        assert "recorded as yours" in panel
        assert "place here" in panel

        # Move it, and check the exact call that went out.
        dev.js("document.querySelectorAll('#ovMove input')[2].value = '0.9';")
        dev.js("[...document.querySelectorAll('#ovMove button')]"
               ".find(b => b.textContent === 'place here').click();")
        for _ in range(100):
            if any(c[0] == "action" for c in calls):
                break
            time.sleep(0.1)
        move = next(c for c in calls if c[0] == "action")
        assert move[1] == "set_var"
        assert move[2]["name"] == "T"
        assert move[2]["row"] == row, "the move must carry the row that was picked"
        assert move[2]["values"][2] == 0.9, move[2]
        for _ in range(60):
            if "step 9" in (dev.js("document.getElementById('ovMoveMsg').innerText") or ""):
                break
            time.sleep(0.1)
        message = dev.js("document.getElementById('ovMoveMsg').innerText")
        assert "step 9" in message and "yours" in message, message
        assert "agent has been told" in message

        # The human can draw an auxiliary object too, which was the one move
        # only the model could make.
        dev.js("[...document.querySelectorAll('#ovMove button')]"
               ".find(b => b.textContent.startsWith('construct')).click();")
        for _ in range(100):
            if any(c[0] == "action" and c[1] == "construct" for c in calls):
                break
            time.sleep(0.1)
        built = next(c for c in calls if c[1] == "construct")
        assert built[2]["ctor"] in ("midpoint", "centroid", "circumcenter", "segment")
        assert built[2]["args"] == ["T"]

        dev.screenshot(tmp_path / "human-move.png")

        dev.js("document.getElementById('btnPause').click();")
        for _ in range(100):
            if any(c[0] == "resume" for c in calls):
                break
            time.sleep(0.1)
        assert any(c[0] == "resume" for c in calls), "resume never reached the service"
        assert "pause" in dev.js("document.getElementById('btnPause').innerText")
    finally:
        dev.close()


if __name__ == "__main__":  # a quick manual check against a running server
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))

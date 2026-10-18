"""Polling bridge: a localhost daemon for apps that can only make OUTBOUND requests.

Most Flue adapters either dispatch scripts through the OS (COM / AppleScript) or talk to an
in-app extension that hosts a tiny HTTP server (``local_http_bridge``). Some hosts, notably
Figma plugins, cannot listen on a port. They can only call out. This transport inverts the
direction:

    agent shell -> <app>_bridge.py --HTTP--> daemon <--long-poll-- in-app poller -> app API

* The daemon binds 127.0.0.1 only, is started on demand, and exits when idle.
* The in-app poller pairs once; afterwards it authenticates with a token
  (``X-Bridge-Token``), the same header ``local_http_bridge`` uses. Pairing is either a short
  one-time code typed into the plugin, or a request the plugin files ("pending") that the agent
  approves from the shell (``/approve``), so the user only has to open the plugin.
* Every request is checked for a loopback ``Host`` (DNS-rebinding defence) and an absent or
  ``null`` ``Origin`` (blocks ordinary web pages). The token is required on top of that.
* Results are shaped before they reach the agent: binary payloads are written to files and
  oversized JSON is spilled to a file, with a short head returned instead.

The session file (same location and ``url``/``token`` keys as other adapters) is
``<APPDATA or ~>/creative-adapters/<session>.json``.
"""

import argparse
import base64
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):  # run directly as the daemon entry point
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridges.local_http_bridge import default_session_file  # noqa: E402

PROTOCOL = 1
DEFAULT_PORT = 47821
POLL_HOLD_S = 20
CLIENT_TTL_S = 10  # a polling client refreshes last_seen every second while it waits, so a closed plugin ages out quickly
PAIR_TTL_S = 300
PAIR_MAX_TRIES = 5
PENDING_TTL_S = 120
PENDING_MAX = 8
IDLE_EXIT_S = 1800
DEFAULT_MAX_CHARS = 8000
HEAD_CHARS = 1500
MAX_BODY_BYTES = 4 << 20
MAX_JOB_BYTES = 24 << 20  # jobs may carry a base64 image
MAX_RESULT_BYTES = 64 << 20

NOT_CONNECTED_HINT = (
    "Ask the user to open the target file and run the Flue Bridge plugin "
    "(Plugins > Development > Flue Bridge). It must stay open while you work."
)


class BridgeError(Exception):
    """An error that maps to an HTTP status and a JSON body."""

    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra

    def body(self):
        return {"ok": False, "code": self.code, "error": str(self), **self.extra}


# --------------------------------------------------------------------------- files


def out_dir(session_name):
    """Per-user scratch directory for screenshots, spilled results and the daemon log."""
    path = Path(tempfile.gettempdir()) / f"flue-{session_name}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def read_session(session_name):
    try:
        with open(default_session_file(session_name), "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_session(session_name, data):
    path = Path(default_session_file(session_name))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(str(tmp), str(path))
    return path


def shape_result(res, out, jid, max_chars, out_path=None, prefix="shot"):
    """Make a plugin result agent-friendly: binaries to files, oversized JSON to a file."""
    if not isinstance(res, dict):
        res = {"ok": True, "result": res}
    blob = res.pop("bin", None)
    if isinstance(blob, dict) and blob.get("b64"):
        data = base64.b64decode(blob["b64"])
        ext = {"image/png": "png", "image/jpeg": "jpg"}.get(blob.get("mime"), "bin")
        target = Path(out_path) if out_path else out / f"{prefix}-{jid}.{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        res["path"] = str(target)
        res["bytes"] = len(data)
    text = json.dumps(res, separators=(",", ":"), ensure_ascii=False)
    if max_chars and len(text) > max_chars:
        spill = out / f"result-{jid}.json"
        spill.write_text(text, encoding="utf-8")
        return {
            "ok": bool(res.get("ok", True)),
            "truncated": True,
            "chars": len(text),
            "file": str(spill),
            "head": text[:HEAD_CHARS],
            "hint": "Result too large; the full JSON was saved to file. Query it with jq/rg or narrow the request.",
        }
    return res


# --------------------------------------------------------------------------- daemon


class Client:
    def __init__(self, cid):
        self.id = cid
        self.file = ""
        self.editor = ""
        self.last_seen = time.time()
        self.busy_until = 0.0
        self.info = {}  # small live facts the plugin reports with each poll (e.g. selection)
        self.queue = deque()


class Job:
    def __init__(self, jid, client_id, payload):
        self.jid = jid
        self.client_id = client_id
        self.payload = payload
        self.state = "queued"  # queued | running | done | abandoned
        self.res = None
        self.event = threading.Event()


class Daemon:
    def __init__(self, app, session_name, port, token, idle_exit_s=IDLE_EXIT_S):
        self.app = app
        self.session_name = session_name
        self.port = port
        self.token = token
        self.idle_exit_s = idle_exit_s
        self.cond = threading.Condition()
        self.clients = {}
        self.jobs = {}
        self.pairing = None
        self.pending = {}  # client id -> {file, editor, ts, approved}
        self.started = time.time()
        self.last_activity = time.time()
        self.server = None
        self.stopping = threading.Event()
        self.out = out_dir(session_name)
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    # -- state helpers (call with self.cond held unless noted)

    def touch(self):
        self.last_activity = time.time()

    def live_clients(self):
        now = time.time()
        return [c for c in self.clients.values() if now - c.last_seen < CLIENT_TTL_S or now < c.busy_until]

    def select_client(self, selector):
        live = self.live_clients()
        if not live:
            raise BridgeError(503, "PLUGIN_NOT_CONNECTED", f"No {self.app} plugin is connected.", hint=NOT_CONNECTED_HINT)
        matches = live
        if selector:
            needle = str(selector).lower()
            matches = [c for c in live if c.id == selector or needle in c.file.lower()]
            if not matches:
                raise BridgeError(404, "NO_SUCH_FILE", f'No connected file matches "{selector}".', clients=[{"id": c.id, "file": c.file} for c in live])
        if len(matches) > 1:
            raise BridgeError(409, "MULTIPLE_CLIENTS", "More than one file is connected; pass --file <name>.", clients=[{"id": c.id, "file": c.file} for c in matches])
        return matches[0]

    # -- operations

    def new_pairing(self):
        with self.cond:
            code = f"{secrets.randbelow(10**6):06d}"
            self.pairing = {"code": code, "expires": time.time() + PAIR_TTL_S, "tries": 0}
        return f"{code[:3]}-{code[3:]}", PAIR_TTL_S

    def try_pair(self, code):
        with self.cond:
            p = self.pairing
            if not p or time.time() > p["expires"]:
                raise BridgeError(403, "NO_PAIRING", "No pairing is in progress. Run `pair` again.")
            p["tries"] += 1
            given = "".join(ch for ch in str(code) if ch.isdigit())
            if not hmac.compare_digest(given, p["code"]):
                if p["tries"] >= PAIR_MAX_TRIES:
                    self.pairing = None
                raise BridgeError(403, "BAD_CODE", "Wrong pairing code.")
            self.pairing = None
            return self.token

    def request_pairing(self, cid, file, editor):
        """A plugin without a token asks to be paired; an authenticated shell command approves it."""
        if not cid or len(cid) > 64:
            raise BridgeError(400, "BAD_REQUEST", "Missing client id.")
        with self.cond:
            self._expire_pending()
            if cid not in self.pending and len(self.pending) >= PENDING_MAX:
                raise BridgeError(429, "TOO_MANY_REQUESTS", "Too many pairing requests waiting.")
            entry = self.pending.setdefault(cid, {"approved": False})
            entry.update(file=str(file or "")[:200], editor=str(editor or "")[:20], ts=time.time())

    def pair_status(self, cid):
        """Plugin side: pending | approved (with the token, delivered once) | none."""
        with self.cond:
            self._expire_pending()
            entry = self.pending.get(cid)
            if not entry:
                return {"state": "none"}
            if entry["approved"]:
                del self.pending[cid]
                return {"state": "approved", "token": self.token}
            return {"state": "pending"}

    def approve(self, file=None, client=None):
        """Shell side: approve exactly one waiting plugin (by file-name fragment or client id)."""
        with self.cond:
            self._expire_pending()
            waiting = [(cid, e) for cid, e in self.pending.items() if not e["approved"]]
            listing = [{"client": cid, "file": e["file"], "ageS": int(time.time() - e["ts"])} for cid, e in waiting]
            if client:
                waiting = [(cid, e) for cid, e in waiting if cid == client]
            if file:
                needle = str(file).lower()
                waiting = [(cid, e) for cid, e in waiting if needle in e["file"].lower()]
            if not waiting:
                raise BridgeError(404, "NO_PENDING", "No plugin is waiting for approval. Ask the user to open Flue Bridge in Figma.", pending=listing)
            if len(waiting) > 1:
                raise BridgeError(409, "MULTIPLE_PENDING", "More than one plugin is waiting; pass --file <name>.", pending=listing)
            cid, entry = waiting[0]
            entry["approved"] = True
            entry["ts"] = time.time()
            return {"client": cid, "file": entry["file"]}

    def _expire_pending(self):
        now = time.time()
        for cid in [c for c, e in self.pending.items() if now - e["ts"] > PENDING_TTL_S]:
            del self.pending[cid]

    def poll(self, cid, file, editor, info=None):
        """Long-poll for the next job for this client. Returns a Job or None."""
        with self.cond:
            client = self.clients.setdefault(cid, Client(cid))
            client.file = file or client.file
            client.editor = editor or client.editor
            if isinstance(info, dict):
                client.info = info
            deadline = time.time() + POLL_HOLD_S
            while not self.stopping.is_set():
                client.last_seen = time.time()
                while client.queue:
                    job = client.queue.popleft()
                    if job.state == "queued":
                        job.state = "running"
                        client.busy_until = time.time() + 600
                        return job
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self.cond.wait(min(remaining, 1.0))
            return None

    def complete(self, cid, jid, res):
        with self.cond:
            client = self.clients.get(cid)
            if client:
                client.busy_until = 0.0
                client.last_seen = time.time()
            job = self.jobs.get(jid)
            if job and job.state == "running":
                job.res = res
                job.state = "done"
                job.event.set()
            self.cond.notify_all()

    def submit(self, payload, selector, timeout):
        with self.cond:
            client = self.select_client(selector)
            job = Job(secrets.token_hex(6), client.id, payload)
            self.jobs[job.jid] = job
            client.queue.append(job)
            self.cond.notify_all()
        finished = job.event.wait(timeout)
        with self.cond:
            self.jobs.pop(job.jid, None)
            if not finished:
                job.state = "abandoned"
                raise BridgeError(
                    504,
                    "TIMEOUT",
                    f"No result after {timeout:g}s. The job may still be running in the app; "
                    "check its state before retrying anything that changes the document.",
                )
            return job

    def status(self):
        with self.cond:
            now = time.time()
            self._expire_pending()
            waiting = [{"client": c, "file": e["file"], "ageS": int(now - e["ts"])} for c, e in self.pending.items() if not e["approved"]]
            return {
                **({"pending": waiting} if waiting else {}),
                "ok": True,
                "app": self.app,
                "protocol": PROTOCOL,
                "pid": os.getpid(),
                "port": self.port,
                "uptimeS": int(now - self.started),
                "clients": [
                    {"id": c.id, "file": c.file, "editor": c.editor, "idleS": int(now - c.last_seen), "busy": now < c.busy_until, **({"info": c.info} if c.info else {})}
                    for c in self.live_clients()
                ],
            }

    def request_stop(self):
        self.stopping.set()
        with self.cond:
            self.cond.notify_all()
        if self.server:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def make_handler(daemon):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FluePolling/1"

        def log_message(self, *args):  # silence default logging
            return

        # -- plumbing

        def _send(self, status, payload=None):
            body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Cache-Control", "no-store")
            if body:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _guard(self, need_token):
            if self.headers.get("Host", "") not in daemon.allowed_hosts:
                raise BridgeError(403, "BAD_HOST", "Unexpected Host header.")
            origin = self.headers.get("Origin")
            if origin not in (None, "null"):
                raise BridgeError(403, "BAD_ORIGIN", "Requests from web pages are not accepted.")
            if need_token:
                given = self.headers.get("X-Bridge-Token", "")
                if not given or not hmac.compare_digest(given, daemon.token):
                    raise BridgeError(401, "BAD_TOKEN", "Missing or invalid bridge token. Pair the plugin again.")

        def _body(self, limit=MAX_BODY_BYTES):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise BridgeError(400, "BAD_REQUEST", "Invalid Content-Length.")
            if length <= 0 or length > limit:
                raise BridgeError(413, "BAD_REQUEST", "Invalid request size.")
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError:
                raise BridgeError(400, "BAD_REQUEST", "Invalid JSON.")

        def _run(self, fn):
            try:
                daemon.touch()
                fn()
            except BridgeError as exc:
                self._send(exc.status, exc.body())
            except Exception as exc:  # never leave a request hanging
                self._send(500, {"ok": False, "code": "INTERNAL", "error": str(exc)})

        # -- routes

        def do_OPTIONS(self):
            def go():
                self._guard(False)
                self._send(204)

            self._run(go)

        def do_GET(self):
            def go():
                url = urlparse(self.path)
                if url.path == "/health":
                    self._guard(False)
                    return self._send(200, {"ok": True, "app": daemon.app, "protocol": PROTOCOL})
                if url.path == "/pair-status":
                    self._guard(False)
                    return self._send(200, daemon.pair_status(parse_qs(url.query).get("client", [""])[0]))
                self._guard(True)
                if url.path == "/status":
                    return self._send(200, daemon.status())
                if url.path == "/poll":
                    q = parse_qs(url.query)
                    info = None
                    raw = q.get("info", [""])[0]
                    if raw and len(raw) <= 1500:
                        try:
                            info = json.loads(raw)
                        except ValueError:
                            info = None
                    job = daemon.poll(q.get("client", [""])[0] or "anon", q.get("file", [""])[0], q.get("editor", [""])[0], info)
                    if job is None:
                        return self._send(204)
                    return self._send(200, {"jid": job.jid, "job": job.payload})
                raise BridgeError(404, "NOT_FOUND", "Unknown path.")

            self._run(go)

        def do_POST(self):
            def go():
                path = urlparse(self.path).path
                if path == "/pair":
                    self._guard(False)
                    body = self._body()
                    token = daemon.try_pair(body.get("code", ""))
                    return self._send(200, {"ok": True, "token": token})
                if path == "/pair-request":
                    self._guard(False)
                    body = self._body()
                    daemon.request_pairing(str(body.get("client", "")), body.get("file"), body.get("editor"))
                    return self._send(200, {"ok": True, "state": "pending"})
                self._guard(True)
                if path == "/approve":
                    body = self._body()
                    return self._send(200, {"ok": True, **daemon.approve(body.get("file"), body.get("client"))})
                if path == "/pairing":
                    code, ttl = daemon.new_pairing()
                    return self._send(200, {"ok": True, "code": code, "expiresInS": ttl})
                if path == "/result":
                    body = self._body(MAX_RESULT_BYTES)
                    daemon.complete(body.get("client", ""), body.get("jid", ""), body.get("res"))
                    return self._send(200, {"ok": True})
                if path == "/job":
                    body = self._body(MAX_JOB_BYTES)
                    job = body.get("job")
                    if not isinstance(job, dict) or not job.get("op"):
                        raise BridgeError(400, "BAD_REQUEST", "Missing job.op.")
                    timeout = float(body.get("timeout") or 60)
                    done = daemon.submit(job, body.get("client"), timeout)
                    max_chars = body.get("maxChars", DEFAULT_MAX_CHARS)
                    shaped = shape_result(done.res, daemon.out, done.jid, max_chars, body.get("out"))
                    return self._send(200, shaped)
                if path == "/shutdown":
                    self._send(200, {"ok": True})
                    return daemon.request_stop()
                raise BridgeError(404, "NOT_FOUND", "Unknown path.")

            self._run(go)

    return Handler


def serve(app, session_name, port, idle_exit_s=IDLE_EXIT_S):
    """Run the daemon in the foreground (this is what ``--serve`` does)."""
    existing = read_session(session_name) or {}
    token = existing.get("token") if isinstance(existing.get("token"), str) and len(existing["token"]) >= 32 else secrets.token_hex(32)
    daemon = Daemon(app, session_name, port, token, idle_exit_s)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = sys.platform != "win32"  # on Windows this would allow a second daemon on the port

    try:
        daemon.server = Server(("127.0.0.1", port), make_handler(daemon))
    except OSError as exc:
        print(json.dumps({"ok": False, "code": "PORT_BUSY", "error": f"Cannot listen on 127.0.0.1:{port}: {exc}"}), file=sys.stderr)
        return 2

    write_session(
        session_name,
        {
            "app": session_name,
            "url": f"http://127.0.0.1:{port}/job",
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "pid": os.getpid(),
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    cutoff = time.time() - 86400
    for old in daemon.out.glob("*"):
        try:
            if old.name != "daemon.log" and old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass

    def watchdog():
        interval = min(5.0, max(0.2, idle_exit_s / 4))
        while not daemon.stopping.wait(interval):
            with daemon.cond:
                idle = time.time() - daemon.last_activity
                busy = bool(daemon.live_clients())
            if idle > daemon.idle_exit_s and not busy:
                print(f"idle for {int(idle)}s with no plugin connected; exiting", file=sys.stderr, flush=True)
                daemon.request_stop()

    threading.Thread(target=watchdog, daemon=True).start()
    print(f"{app} polling bridge listening on 127.0.0.1:{port} (pid {os.getpid()})", file=sys.stderr, flush=True)
    try:
        daemon.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.server.server_close()
    return 0


# --------------------------------------------------------------------------- client side


def resolve_port(session_name, explicit=None):
    if explicit:
        return int(explicit)
    env = os.environ.get("FLUE_BRIDGE_PORT") or os.environ.get(f"FLUE_{session_name.upper()}_PORT")
    if env:
        return int(env)
    session = read_session(session_name)
    if session and isinstance(session.get("port"), int):
        return session["port"]
    return DEFAULT_PORT


def http_json(method, url, body=None, token=None, timeout=30):
    """Return (status, parsed_json_or_None). Raises URLError if nothing is listening."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Bridge-Token"] = token
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, (json.loads(raw.decode("utf-8")) if raw else None)
    except ValueError:
        return status, {"ok": False, "error": raw.decode("utf-8", "replace")[:300]}


def daemon_alive(port, app=None):
    try:
        status, body = http_json("GET", f"http://127.0.0.1:{port}/health", timeout=1.5)
    except (urllib.error.URLError, OSError):
        return False
    return status == 200 and isinstance(body, dict) and body.get("protocol") == PROTOCOL and (app is None or body.get("app") == app)


def spawn_daemon(app, session_name, port):
    log = out_dir(session_name) / "daemon.log"
    args = [sys.executable, str(Path(__file__).resolve()), "--serve", "--app", app, "--session", session_name, "--port", str(port)]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": open(log, "ab")}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)
    return log


def ensure_daemon(app, session_name, port=None):
    """Return (base_url, token), starting the daemon if it is not running."""
    port = resolve_port(session_name, port)
    if not daemon_alive(port, app):
        log = spawn_daemon(app, session_name, port)
        for _ in range(60):
            time.sleep(0.1)
            if daemon_alive(port, app):
                break
        else:
            tail = ""
            try:
                tail = log.read_text(encoding="utf-8", errors="replace")[-400:]
            except OSError:
                pass
            raise BridgeError(500, "DAEMON_START_FAILED", f"Could not start the {app} bridge daemon on port {port}. {tail.strip()}")
    session = read_session(session_name)
    if not session or not session.get("token"):
        raise BridgeError(500, "NO_SESSION", f"Session file for {session_name} is missing or incomplete.")
    return f"http://127.0.0.1:{port}", session["token"]


def run_job(app, session_name, job, *, port=None, timeout=60, client=None, max_chars=DEFAULT_MAX_CHARS, out=None):
    """Send one job {op, ...} through the daemon. Returns the shaped result dict."""
    base, token = ensure_daemon(app, session_name, port)
    body = {"job": job, "timeout": timeout, "client": client, "maxChars": max_chars, "out": out}
    status, obj = http_json("POST", f"{base}/job", body, token, timeout=timeout + 15)
    if not isinstance(obj, dict):
        raise BridgeError(500, "BAD_RESPONSE", f"Unexpected response from daemon (HTTP {status}).")
    return obj


def admin(app, session_name, path, *, port=None, method="POST", body=None):
    base, token = ensure_daemon(app, session_name, port)
    status, obj = http_json(method, f"{base}{path}", (body or {}) if method == "POST" else None, token)
    return obj if isinstance(obj, dict) else {"ok": False, "error": f"HTTP {status}"}


def stop_daemon(app, session_name, *, port=None):
    port = resolve_port(session_name, port)
    if not daemon_alive(port, app):
        return {"ok": True, "stopped": False, "note": "bridge daemon was not running"}
    session = read_session(session_name) or {}
    status, obj = http_json("POST", f"http://127.0.0.1:{port}/shutdown", {}, session.get("token"))
    return {"ok": status == 200, "stopped": status == 200}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the polling bridge daemon (normally started automatically).")
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--idle-exit", type=int, default=IDLE_EXIT_S, help="Exit after this many idle seconds.")
    args = parser.parse_args(argv)
    return serve(args.app, args.session, args.port, args.idle_exit)


if __name__ == "__main__":
    raise SystemExit(main())

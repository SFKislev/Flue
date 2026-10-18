"""End-to-end test of the Figma adapter, minus Figma itself.

    figma_bridge.py (real) -> daemon (real, auto-started) <- FakePlugin (plays ui.html)
                                                               -> node_runner.js: plugin/code.js (real) + fake Figma API

Everything except the Figma application and its WebView is the shipped code. Run:
    python -m unittest adapters/figma_adapter/tests/test_e2e.py -v
"""

import base64
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent
REPO = ADAPTER.parents[1]
sys.path.insert(0, str(REPO))

from bridges import polling_bridge as pb  # noqa: E402

BRIDGE = ADAPTER / "figma_bridge.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("figma_bridge_under_test", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NodeRunner:
    """The real plugin code on a fake Figma, driven over JSON lines."""

    def __init__(self):
        self.proc = subprocess.Popen(["node", str(HERE / "node_runner.js")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.lock = threading.Lock()

    def call(self, jid, job):
        with self.lock:
            self.proc.stdin.write(json.dumps({"jid": jid, "job": job}) + "\n")
            self.proc.stdin.flush()
            return json.loads(self.proc.stdout.readline())["res"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=5)


class FakePlugin(threading.Thread):
    """Plays the plugin window: pairs, long-polls, forwards jobs to the node runner, posts results."""

    def __init__(self, base, node, cid, file, token, tag=None):
        super().__init__(daemon=True)
        self.base, self.node, self.cid, self.file, self.token, self.tag = base, node, cid, file, token, tag
        self.stop_flag = False
        self.hang_s = 0

    def run(self):
        while not self.stop_flag:
            try:
                q = f"client={self.cid}&file={urllib.request.quote(self.file)}&editor=figma"
                status, body = pb.http_json("GET", f"{self.base}/poll?{q}", token=self.token, timeout=30)
            except Exception:
                return
            if status != 200 or not body:
                continue
            if self.hang_s:
                time.sleep(self.hang_s)
            res = self.node.call(body["jid"], body["job"])
            if self.tag:
                res["via"] = self.tag
            try:
                pb.http_json("POST", f"{self.base}/result", {"client": self.cid, "jid": body["jid"], "res": res}, self.token)
            except Exception:
                return


class E2E(unittest.TestCase):
    """Ordered scenario: tests share one daemon and one fake plugin, so they are numbered."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.env = {**os.environ, "APPDATA": cls.tmp.name, "HOME": cls.tmp.name, "TMPDIR": cls.tmp.name, "TEMP": cls.tmp.name,
                   "TMP": cls.tmp.name, "FLUE_FIGMA_PORT": str(cls.port)}
        # the test process must see the same isolated session file the CLI subprocess sees
        cls.env_patch = unittest.mock.patch.dict(os.environ, cls.env)
        cls.env_patch.start()
        cls.node = NodeRunner()
        cls.plugin = None
        cls.plugin2 = None

    @classmethod
    def tearDownClass(cls):
        for p in (cls.plugin, cls.plugin2):
            if p:
                p.stop_flag = True
        cls.cli("stop")
        cls.node.close()
        cls.env_patch.stop()
        cls.tmp.cleanup()

    @classmethod
    def cli(cls, *args, stdin=None):
        proc = subprocess.run([sys.executable, str(BRIDGE), *args], input=stdin, capture_output=True, text=True, env=cls.env, timeout=90)

        def parse(text):
            text = text.strip()
            return json.loads(text) if text else None

        return proc.returncode, parse(proc.stdout), parse(proc.stderr)

    def raw(self, method, path, headers=None, body=None):
        """Direct HTTP to the daemon (for security checks). Returns (status, headers, text)."""
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    # ------------------------------------------------------------------ scenario

    def test_01_not_connected_gives_actionable_error(self):
        code, out, err = self.cli("ctx")
        self.assertEqual(code, 1)
        self.assertIsNone(out)
        self.assertEqual(err["code"], "PLUGIN_NOT_CONNECTED")
        self.assertIn("Flue Bridge", err["hint"])
        session = pb.read_session("figma")
        self.assertEqual(session["port"], self.port)
        self.assertEqual(len(session["token"]), 64)
        if os.name != "nt":
            mode = oct(Path(pb.default_session_file("figma")).stat().st_mode & 0o777)
            self.assertEqual(mode, "0o600", "session file holds the token and must be private")

    def test_02_security_checks(self):
        token = pb.read_session("figma")["token"]
        # wrong Host (DNS rebinding)
        status, _, text = self.raw("GET", "/health", {"Host": "evil.example"})
        self.assertEqual(status, 403)
        # a web page origin
        status, _, text = self.raw("GET", "/health", {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("BAD_ORIGIN", text)
        # the plugin iframe's null origin is accepted
        status, _, _ = self.raw("GET", "/health", {"Origin": "null"})
        self.assertEqual(status, 200)
        # token required
        status, _, text = self.raw("GET", "/status")
        self.assertEqual(status, 401)
        status, _, _ = self.raw("GET", "/status", {"X-Bridge-Token": "0" * 64})
        self.assertEqual(status, 401)
        status, _, _ = self.raw("GET", "/status", {"X-Bridge-Token": token})
        self.assertEqual(status, 200)
        # CORS preflight carries what a null-origin iframe needs
        status, headers, _ = self.raw("OPTIONS", "/poll", {"Origin": "null", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-bridge-token"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("X-Bridge-Token", headers.get("Access-Control-Allow-Headers", ""))
        self.assertEqual(headers.get("Access-Control-Allow-Private-Network"), "true")

    def test_03_pairing(self):
        # no pairing in progress yet
        status, _, text = self.raw("POST", "/pair", {"Content-Type": "application/json"}, json.dumps({"code": "000-000"}).encode())
        self.assertEqual(status, 403)
        code, out, _ = self.cli("pair", "--code")
        self.assertEqual(code, 0)
        self.assertRegex(out["code"], r"^\d{3}-\d{3}$")
        wrong = "999-999" if out["code"] != "999-999" else "111-111"
        status, _, text = self.raw("POST", "/pair", {"Content-Type": "application/json"}, json.dumps({"code": wrong}).encode())
        self.assertEqual(status, 403)
        self.assertIn("BAD_CODE", text)
        status, _, text = self.raw("POST", "/pair", {"Content-Type": "application/json"}, json.dumps({"code": out["code"]}).encode())
        self.assertEqual(status, 200)
        token = json.loads(text)["token"]
        self.assertEqual(token, pb.read_session("figma")["token"])
        # single use
        status, _, _ = self.raw("POST", "/pair", {"Content-Type": "application/json"}, json.dumps({"code": out["code"]}).encode())
        self.assertEqual(status, 403)
        type(self).plugin = FakePlugin(self.base, self.node, "c-one", "Design System.fig", token)
        self.plugin.start()
        time.sleep(0.5)

    def test_03b_pairing_by_approval(self):
        """The plugin files a request; the agent approves it from the shell (no code to type)."""
        hdr = {"Content-Type": "application/json"}
        code, _, err = self.cli("pair")
        self.assertNotEqual(code, 0)
        self.assertEqual(err["code"], "NO_PENDING")
        # web pages cannot file requests; the plugin iframe (Origin: null) can
        status, _, _ = self.raw("POST", "/pair-request", {**hdr, "Origin": "https://evil.example"}, json.dumps({"client": "c-x", "file": "X"}).encode())
        self.assertEqual(status, 403)
        status, _, _ = self.raw("POST", "/pair-request", {**hdr, "Origin": "null"}, json.dumps({"client": "c-new", "file": "Game.fig"}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.raw("GET", "/pair-status?client=c-new", {"Origin": "null"})[2])["state"], "pending")
        # an unknown client never gets a token
        self.assertEqual(json.loads(self.raw("GET", "/pair-status?client=guess", {"Origin": "null"})[2])["state"], "none")
        _, st, _ = self.cli("status")
        self.assertEqual(st["pending"][0]["file"], "Game.fig")
        # wrong file name does not approve; a second waiting plugin makes a bare approve ambiguous
        code, _, err = self.cli("pair", "--file", "nope")
        self.assertEqual(err["code"], "NO_PENDING")
        self.raw("POST", "/pair-request", {**hdr, "Origin": "null"}, json.dumps({"client": "c-two", "file": "Other.fig"}).encode())
        code, _, err = self.cli("pair")
        self.assertEqual(err["code"], "MULTIPLE_PENDING")
        code, out, _ = self.cli("pair", "--file", "Game")
        self.assertEqual(code, 0)
        self.assertEqual(out["file"], "Game.fig")
        body = json.loads(self.raw("GET", "/pair-status?client=c-new", {"Origin": "null"})[2])
        self.assertEqual(body["state"], "approved")
        self.assertEqual(body["token"], pb.read_session("figma")["token"])
        # the token is handed over once
        self.assertEqual(json.loads(self.raw("GET", "/pair-status?client=c-new", {"Origin": "null"})[2])["state"], "none")
        code, _, err = self.cli("pair", "--file", "Game")
        self.assertEqual(err["code"], "NO_PENDING")
        # leave no pending request behind for the other tests
        self.cli("pair", "--file", "Other")
        self.raw("GET", "/pair-status?client=c-two", {"Origin": "null"})

    def test_04_pairing_locks_after_too_many_wrong_codes(self):
        code, out, _ = self.cli("pair", "--code")
        for _ in range(pb.PAIR_MAX_TRIES):
            self.raw("POST", "/pair", {"Content-Type": "application/json"}, json.dumps({"code": "000-001"}).encode())
        status, _, _ = self.raw("POST", "/pair", {"Content-Type": "application/json"}, json.dumps({"code": out["code"]}).encode())
        self.assertEqual(status, 403, "the real code no longer works after brute-force attempts")

    def test_05_status_and_ctx(self):
        code, out, _ = self.cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(out["plugin"], "connected")
        self.assertEqual(out["clients"][0]["file"], "Design System.fig")
        code, out, _ = self.cli("ctx")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["file"], "Test file")
        self.assertTrue(out["caps"]["eval"])

    def test_06_build_tree_get_set_find(self):
        spec = {"nodes": [{"t": "frame", "name": "Card", "w": 320, "layout": "v", "gap": 8, "pad": 16, "fill": "#ffffff", "radius": 12, "as": "card",
                           "c": [{"t": "text", "text": "Title", "size": 20, "weight": 700, "as": "title"},
                                 {"t": "text", "text": "Body", "size": 14, "w": "fill"}]}]}
        code, out, err = self.cli("build", "--stdin", stdin=json.dumps(spec))
        self.assertEqual(code, 0, err)
        self.assertEqual(out["created"], 3)
        type(self).ids = out["ids"]

        code, out, _ = self.cli("tree", "--depth", "3", "--fields", "fill,text")
        self.assertEqual(code, 0)
        self.assertEqual(out["cols"][:4], ["d", "id", "type", "name"])
        self.assertEqual([r[2] for r in out["rows"]], ["FRAME", "TEXT", "TEXT"])
        self.assertEqual(out["rows"][1][out["cols"].index("text")], "Title")

        code, out, _ = self.cli("get", self.ids["card"], "--fields", "layout,gap,pad,fill")
        self.assertEqual(out["node"]["layout"], "v")
        self.assertEqual(out["node"]["pad"], 16)

        code, out, err = self.cli("set", self.ids["title"], "text=Hello", "fill=#ff0000", "weight=500")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["set"], 1)
        code, out, _ = self.cli("get", self.ids["title"], "--fields", "text,fill,font")
        self.assertEqual((out["node"]["text"], out["node"]["fill"], out["node"]["font"]), ("Hello", "#ff0000", ["Inter", "Medium"]))

        code, out, _ = self.cli("find", "--type", "text", "--text", "hel")
        self.assertEqual(len(out["rows"]), 1)

    def test_07_errors_use_stderr_and_exit_code(self):
        code, out, err = self.cli("set", self.ids["card"], "bogus=1")
        self.assertEqual(code, 1)
        self.assertIsNone(out)
        self.assertEqual(err["code"], "BAD_PROP")
        code, out, err = self.cli("get", "9:999")
        self.assertEqual((code, err["code"]), (1, "NODE_NOT_FOUND"))

    def test_08_shot_writes_a_file(self):
        dest = Path(self.tmp.name) / "shots" / "card.png"
        code, out, err = self.cli("shot", self.ids["card"], "-o", str(dest))
        self.assertEqual(code, 0, err)
        self.assertEqual(out["path"], str(dest.resolve()))
        self.assertNotIn("bin", out)
        self.assertEqual(dest.read_bytes()[1:4], b"PNG")
        code, out, _ = self.cli("shot", self.ids["card"])
        self.assertTrue(Path(out["path"]).exists(), "default location is inside the temp folder")

    def test_09_raw_script_and_json_jobs_via_stdin(self):
        code, out, err = self.cli("--stdin", stdin="console.log('hi'); return figma.currentPage.children.length;")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["result"], 1)
        self.assertEqual(out["logs"], ["hi"])
        code, out, _ = self.cli("--stdin", stdin='{"op":"ctx"}')
        self.assertEqual(out["file"], "Test file")
        code, out, _ = self.cli("--stdin", stdin='[{"op":"find","type":"TEXT"},{"op":"ctx"}]')
        self.assertEqual(len(out["results"]), 2)
        self.assertNotIn("ok", out["results"][0])
        code, out, err = self.cli("--stdin", stdin='[{"op":"ctx"},{"op":"get","id":"9:999"},{"op":"ctx"}]')
        self.assertEqual(code, 1)
        self.assertEqual(err["failedAt"], 1)
        self.assertEqual(len(err["results"]), 1, "work done before the failure is reported")
        code, out, err = self.cli("--stdin", stdin="throw new Error('boom')")
        self.assertEqual((code, err["code"], err["error"]), (1, "SCRIPT_ERROR", "boom"))

    def test_10_large_results_spill_to_a_file(self):
        many = {"nodes": [{"t": "text", "text": f"Row number {i}"} for i in range(60)]}
        self.assertEqual(self.cli("build", "--stdin", stdin=json.dumps(many))[0], 0)
        code, out, _ = self.cli("tree", "--max", "500", "--max-chars", "600")
        self.assertEqual(code, 0)
        self.assertTrue(out["truncated"])
        self.assertLessEqual(len(out["head"]), pb.HEAD_CHARS)
        full = json.loads(Path(out["file"]).read_text())
        self.assertGreater(len(full["rows"]), 60)
        self.assertEqual(out["chars"], len(json.dumps(full, separators=(",", ":"), ensure_ascii=False)))
        # and the cap can be turned off
        code, out, _ = self.cli("tree", "--max", "500", "--max-chars", "0")
        self.assertNotIn("truncated", out)

    def test_11_timeout_is_reported_and_late_result_is_dropped(self):
        self.plugin.hang_s = 2.5
        code, out, err = self.cli("ctx", "--timeout", "1")
        self.assertEqual((code, err["code"]), (1, "TIMEOUT"))
        self.assertIn("before retrying", err["error"])
        time.sleep(3.0)  # the hung job finishes late; its result must be ignored
        self.plugin.hang_s = 0
        code, out, err = self.cli("ctx")
        self.assertEqual(code, 0, err)

    def test_12_two_files_need_a_selector(self):
        code, out, _ = self.cli("pair", "--code")
        status, _, text = self.raw("POST", "/pair", {"Content-Type": "application/json"}, json.dumps({"code": out["code"]}).encode())
        token = json.loads(text)["token"]
        type(self).plugin2 = FakePlugin(self.base, self.node, "c-two", "Marketing site", token, tag="two")
        self.plugin2.start()
        time.sleep(0.5)
        code, out, err = self.cli("ctx")
        self.assertEqual((code, err["code"]), (1, "MULTIPLE_CLIENTS"))
        self.assertEqual({c["file"] for c in err["clients"]}, {"Design System.fig", "Marketing site"})
        code, out, _ = self.cli("ctx", "--target", "market")
        self.assertEqual(out.get("via"), "two")
        code, out, err = self.cli("ctx", "--target", "nothing-like-this")
        self.assertEqual(err["code"], "NO_SUCH_FILE")
        self.plugin2.stop_flag = True

    def test_13_stop(self):
        code, out, _ = self.cli("stop")
        self.assertEqual(out["stopped"], True)
        time.sleep(0.3)
        self.assertFalse(pb.daemon_alive(self.port))
        code, out, _ = self.cli("stop")
        self.assertEqual(out["stopped"], False)


class Units(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_cli()

    def test_jobs_from_text(self):
        j = self.cli.jobs_from_text
        self.assertEqual(j("return 1"), [{"op": "eval", "code": "return 1"}])
        self.assertEqual(j('{"op":"ctx"}'), [{"op": "ctx"}])
        self.assertEqual(j('[{"op":"ctx"},{"op":"tree"}]')[1]["op"], "tree")
        # JS that merely starts with a brace is still JS
        self.assertEqual(j("{ const x = 1; return x }")[0]["op"], "eval")
        # JSON without an op is not a job
        self.assertEqual(j('{"nodes":[]}')[0]["op"], "eval")
        with self.assertRaises(ValueError):
            j("   ")

    def test_set_argument_parsing(self):
        args = self.cli.build_parser().parse_args(["set", "12:3", "12:4", "fill=#fff", "w=100", "text=hi", "pad=[8,16]", "vis=false"])
        jobs, _ = self.cli.jobs_from_args(args)
        self.assertEqual(jobs[0]["ids"], ["12:3", "12:4"])
        self.assertEqual(jobs[0]["props"], {"fill": "#fff", "w": 100, "text": "hi", "pad": [8, 16], "vis": False})
        with self.assertRaises(ValueError):
            self.cli.jobs_from_args(self.cli.build_parser().parse_args(["set", "12:3"]))

    def test_tree_find_arguments_skip_unset_options(self):
        p = self.cli.build_parser()
        jobs, _ = self.cli.jobs_from_args(p.parse_args(["tree"]))
        self.assertEqual(jobs, [{"op": "tree"}])
        jobs, _ = self.cli.jobs_from_args(p.parse_args(["find", "--type", "text,frame", "--in", "1:2", "--limit", "5"]))
        self.assertEqual(jobs[0], {"op": "find", "type": ["text", "frame"], "in": "1:2", "limit": 5})

    def test_new_commands_translate_to_jobs(self):
        p = self.cli.build_parser()
        jobs, extra = self.cli.jobs_from_args(p.parse_args(["sheet", "1:2", "1:3", "--cols", "2", "--cell", "300", "-o", "x.png"]))
        self.assertEqual(jobs, [{"op": "sheet", "ids": ["1:2", "1:3"], "cols": 2, "cell": 300}])
        self.assertTrue(extra["out"].endswith("x.png"))
        jobs, _ = self.cli.jobs_from_args(p.parse_args(["sheet", "9:9", "--children", "--no-labels"]))
        self.assertEqual(jobs, [{"op": "sheet", "ids": ["9:9"], "children": True, "labels": False}])
        jobs, _ = self.cli.jobs_from_args(p.parse_args(["checkpoint", "Before", "--note", "n"]))
        self.assertEqual(jobs, [{"op": "checkpoint", "title": "Before", "note": "n"}])
        jobs, _ = self.cli.jobs_from_args(p.parse_args(["find", "--tagged"]))
        self.assertEqual(jobs, [{"op": "find", "tagged": True}])
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "pic.png"
            img.write_bytes(b"\x89PNG\r\n")
            jobs, _ = self.cli.jobs_from_args(p.parse_args(["image", str(img), "--w", "300", "--at", "10,20", "--mode", "fit"]))
            job = jobs[0]
            self.assertEqual((job["op"], job["w"], job["at"], job["mode"], job["name"]), ("image", 300.0, [10.0, 20.0], "FIT", "pic"))
            self.assertEqual(base64.b64decode(job["b64"]), b"\x89PNG\r\n")
            bad = Path(d) / "pic.webp"
            bad.write_bytes(b"x")
            with self.assertRaises(ValueError):
                self.cli.jobs_from_args(p.parse_args(["image", str(bad)]))

    def test_shape_result(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            small = pb.shape_result({"ok": True, "n": 1}, out, "j1", 100)
            self.assertEqual(small, {"ok": True, "n": 1})
            png = base64.b64encode(b"\x89PNG\r\n").decode()
            shaped = pb.shape_result({"ok": True, "bin": {"mime": "image/png", "b64": png}}, out, "j2", 1000)
            self.assertEqual(Path(shaped["path"]).read_bytes(), b"\x89PNG\r\n")
            self.assertNotIn("bin", shaped)
            big = pb.shape_result({"ok": True, "rows": [[i] * 10 for i in range(100)]}, out, "j3", 200)
            self.assertTrue(big["truncated"])
            self.assertEqual(len(json.loads(Path(big["file"]).read_text())["rows"]), 100)
            self.assertTrue(pb.shape_result({"ok": False, "error": "x" * 500}, out, "j4", 100)["truncated"])
            self.assertFalse(pb.shape_result({"ok": False, "error": "x" * 500}, out, "j4", 100)["ok"])


class IdleExit(unittest.TestCase):
    def test_daemon_exits_when_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = free_port()
            env = {**os.environ, "APPDATA": tmp, "HOME": tmp, "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp}
            proc = subprocess.Popen([sys.executable, str(REPO / "bridges" / "polling_bridge.py"), "--serve", "--app", "Figma", "--session", "figma", "--port", str(port), "--idle-exit", "1"], env=env, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    if pb.daemon_alive(port):
                        break
                    time.sleep(0.1)
                self.assertTrue(pb.daemon_alive(port))
                self.assertEqual(proc.wait(timeout=10), 0, "idle daemon should exit cleanly")
            finally:
                if proc.poll() is None:
                    proc.kill()

    def test_port_in_use_is_reported(self):
        with socket.socket() as s, tempfile.TemporaryDirectory() as tmp:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            env = {**os.environ, "APPDATA": tmp, "HOME": tmp, "TMPDIR": tmp}
            proc = subprocess.run([sys.executable, str(REPO / "bridges" / "polling_bridge.py"), "--serve", "--app", "Figma", "--session", "figma", "--port", str(s.getsockname()[1])], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("PORT_BUSY", proc.stderr)


if __name__ == "__main__":
    unittest.main()

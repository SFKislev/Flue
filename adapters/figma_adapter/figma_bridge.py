#!/usr/bin/env python3
"""Flue bridge for Figma.

    agent shell -> figma_bridge.py -> local daemon <- (poll) Flue Bridge plugin -> Figma Plugin API

Flue contract (same as every adapter): code/jobs in via argv, --stdin or --file; JSON on stdout
on success; JSON on stderr and a non-zero exit on failure. On top of that this bridge has compact
subcommands (ctx, tree, get, find, set, build, shot, sheet, image, checkpoint) whose outputs are kept small on purpose.

Raw scripts still work:  figma_bridge.py --stdin   (JS body; has `figma`, `H`, `S`, `console`)
JSON jobs also work:     echo '{"op":"ctx"}' | figma_bridge.py --stdin
                         echo '[{"op":"find","type":"TEXT"},{"op":"ctx"}]' | figma_bridge.py --stdin
"""

import argparse
import base64
import json
import re
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridges import polling_bridge as pb  # noqa: E402

APP = "Figma"
SESSION = "figma"
PLUGIN_DIR = Path(__file__).resolve().parent / "plugin"
COMMANDS = ("ctx", "tree", "get", "find", "set", "build", "shot", "sheet", "image", "checkpoint", "eval", "pair", "status", "stop", "manifest")
IMAGE_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
MAX_IMAGE_BYTES = 12 << 20


# --------------------------------------------------------------------------- output


def dump(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def ok(obj):
    print(dump(obj))
    return 0


def fail(obj, code=1):
    print(dump(obj), file=sys.stderr)
    return code


# --------------------------------------------------------------------------- args


def common():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--timeout", type=float, default=60, help="Seconds to wait for Figma (default 60).")
    p.add_argument("--target", help="Which open Figma file (name fragment or client id) when several are connected.")
    p.add_argument("--max-chars", type=int, default=pb.DEFAULT_MAX_CHARS, help="Cap on result size; bigger results are saved to a file (0 = no cap).")
    p.add_argument("--port", type=int, help="Daemon port (default 47821, or FLUE_FIGMA_PORT).")
    return p


def csv(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def build_parser():
    c = common()
    parser = argparse.ArgumentParser(prog="figma_bridge.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("ctx", parents=[c], help="File, page, selection, viewport and capabilities (read-only).")

    p = sub.add_parser("tree", parents=[c], help="Compact outline as rows. Defaults to the selection, else the page.")
    p.add_argument("id", nargs="?", help="Start at this node id.")
    p.add_argument("--depth", type=int, help="Levels below the start (default 2).")
    p.add_argument("--max", type=int, help="Row cap (default 150).")
    p.add_argument("--fields", help="Extra columns, comma separated (fill,stroke,layout,gap,pad,text,...).")
    p.add_argument("--page", help="Read another page by name without switching to it.")

    p = sub.add_parser("get", parents=[c], help="Properties of one or more nodes.")
    p.add_argument("ids", nargs="+")
    p.add_argument("--fields", help="Comma separated, or 'all'. Default is a common set; inapplicable fields are omitted.")

    p = sub.add_parser("find", parents=[c], help="Find nodes by type / name / text.")
    p.add_argument("--type", help="Node type, e.g. TEXT or FRAME (comma separated for several).")
    p.add_argument("--name", help="Case-insensitive substring of the layer name.")
    p.add_argument("--re", help="Regex on the layer name.")
    p.add_argument("--text", help="Substring of a text node's characters.")
    p.add_argument("--in", dest="scope", help="Search inside this node id (default: current page).")
    p.add_argument("--limit", type=int, help="Max rows (default 30).")
    p.add_argument("--fields", help="Extra columns.")
    p.add_argument("--tagged", action="store_true", help="Only top-level nodes created by `build` (tagged with plugin data).")

    p = sub.add_parser("set", parents=[c], help="set <id>... key=value ...  (values are parsed as JSON when possible).")
    p.add_argument("items", nargs="+", metavar="id|key=value")

    p = sub.add_parser("build", parents=[c], help="Create nodes from a JSON spec (see APP.md).")
    p.add_argument("spec", nargs="?", help="Spec as a JSON string.")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--file", help="Read the spec from a file.")
    p.add_argument("--parent", help="Add inside this node id (default: current page).")
    p.add_argument("--at", help="x,y for the first top-level node.")
    p.add_argument("--select", action="store_true", help="Select the created nodes.")

    p = sub.add_parser("shot", parents=[c], help="Export a node as a PNG/JPG file and return its path.")
    p.add_argument("id", nargs="?", help="Node id (default: first selected node).")
    p.add_argument("--scale", type=float)
    p.add_argument("--maxpx", type=int, help="Longest side cap in px (default 1024).")
    p.add_argument("--fmt", choices=["png", "jpg"], default="png")
    p.add_argument("-o", "--out", help="Write here instead of the temp folder.")

    p = sub.add_parser("sheet", parents=[c], help="Contact sheet: several nodes in ONE labelled image (one image to look at instead of many).")
    p.add_argument("ids", nargs="+", help="Node ids (or one id whose children are all shown, with --children).")
    p.add_argument("--children", action="store_true", help="Show the children of the single given node (e.g. all screens on a page frame).")
    p.add_argument("--cols", type=int, help="Columns (default: fit the count).")
    p.add_argument("--cell", type=int, help="Width of each cell in px (default 360).")
    p.add_argument("--maxpx", type=int, help="Cap on the sheet's width in px (default 1600).")
    p.add_argument("--no-labels", action="store_true")
    p.add_argument("-o", "--out", help="Write here instead of the temp folder.")

    p = sub.add_parser("image", parents=[c], help="Put a local PNG/JPG/GIF into the file: new rectangle, or an image fill on a node.")
    p.add_argument("file", help="Path to the image.")
    p.add_argument("--fill", help="Apply as an image fill to this node id instead of creating a rectangle.")
    p.add_argument("--parent", help="Create the rectangle inside this node id (default: current page).")
    p.add_argument("--at", help="x,y for the new rectangle.")
    p.add_argument("--w", type=float, help="Width of the new rectangle (height keeps the aspect ratio).")
    p.add_argument("--mode", choices=["fill", "fit", "crop", "tile"], default="fill", help="Scale mode (default fill).")
    p.add_argument("--name", help="Layer name.")

    p = sub.add_parser("checkpoint", parents=[c], help="Save a named version in Figma's version history (only when the user asks, or before a big edit they approved).")
    p.add_argument("title")
    p.add_argument("--note", help="Description.")

    p = sub.add_parser("eval", parents=[c], help="Run a JS body in the plugin (async; has figma, H, S, console).")
    p.add_argument("code", nargs="?")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--file")

    p = sub.add_parser("pair", parents=[c], help="Approve the plugin that is waiting (normal first-run path), or print a one-time code to type in the plugin.")
    p.add_argument("--approve", action="store_true", help="Approve the one plugin window that is waiting for approval.")
    p.add_argument("--file", help="With --approve: only the waiting plugin whose file name contains this.")
    p.add_argument("--code", action="store_true", help="Print a one-time 6-digit code instead (fallback: type it into the plugin's expanded panel).")
    sub.add_parser("status", parents=[c], help="Daemon and plugin connection state.")
    sub.add_parser("stop", parents=[c], help="Stop the background daemon.")
    p = sub.add_parser("manifest", help="Rewrite the plugin manifest and UI for a different port.")
    p.add_argument("--port", type=int, required=True)
    return parser


def legacy_parser():
    p = argparse.ArgumentParser(prog="figma_bridge.py", parents=[common()], description="Flue contract: script or JSON job(s) via argv, --stdin or --file.")
    p.add_argument("code", nargs="?", help="JS body or JSON job(s).")
    p.add_argument("--stdin", action="store_true", help="Read from stdin.")
    p.add_argument("--file", help="Read from a file.")
    return p


def read_text(args):
    if getattr(args, "stdin", False):
        return sys.stdin.read()
    if getattr(args, "file", None):
        with open(args.file, "r", encoding="utf-8-sig") as handle:
            return handle.read()
    code = getattr(args, "code", None) or getattr(args, "spec", None)
    if code:
        return code
    raise ValueError("No input. Use --stdin, --file, or pass it as an argument.")


def jobs_from_text(text):
    """JSON job(s) if the text is one, otherwise a raw JS script to eval."""
    if not text.strip():
        raise ValueError("Input is empty.")
    if text.lstrip()[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict) and "op" in data:
            return [data]
        if isinstance(data, list) and data and all(isinstance(x, dict) and "op" in x for x in data):
            return data
    return [{"op": "eval", "code": text}]


def parse_value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def drop_none(d):
    return {k: v for k, v in d.items() if v is not None and v is not False}


def jobs_from_args(args):
    """Translate a parsed subcommand into (jobs, extra) where extra carries transport options."""
    cmd = args.cmd
    extra = {}
    if cmd == "ctx":
        return [{"op": "ctx"}], extra
    if cmd == "tree":
        return [drop_none({"op": "tree", "id": args.id, "depth": args.depth, "max": args.max, "fields": csv(args.fields), "page": args.page})], extra
    if cmd == "get":
        key = "ids" if len(args.ids) > 1 else "id"
        return [drop_none({"op": "get", key: args.ids if len(args.ids) > 1 else args.ids[0], "fields": csv(args.fields)})], extra
    if cmd == "find":
        types = csv(args.type)
        return [drop_none({"op": "find", "type": types, "name": args.name, "re": args.re, "text": args.text, "in": args.scope, "limit": args.limit, "fields": csv(args.fields), "tagged": args.tagged})], extra
    if cmd == "set":
        ids, props = [], {}
        for item in args.items:
            if "=" in item and not re.fullmatch(r"\d+:\d+", item):
                key, _, raw = item.partition("=")
                props[key] = parse_value(raw)
            else:
                ids.append(item)
        if not ids or not props:
            raise ValueError("set needs at least one node id and one key=value.")
        return [{"op": "set", "ids": ids, "props": props}], extra
    if cmd == "build":
        spec = json.loads(read_text(args))
        job = {"op": "build"}
        if isinstance(spec, list):
            job["nodes"] = spec
        elif "nodes" in spec or "t" in spec:
            job.update(spec)
        else:
            raise ValueError('build spec needs {"nodes":[...]} or a node object with "t".')
        if args.parent:
            job["parent"] = args.parent
        if args.at:
            job["at"] = [float(v) for v in args.at.split(",")]
        if args.select:
            job["select"] = True
        return [job], extra
    if cmd == "shot":
        job = drop_none({"op": "shot", "id": args.id, "scale": args.scale, "maxpx": args.maxpx, "fmt": args.fmt.upper()})
        if args.out:
            extra["out"] = str(Path(args.out).resolve())
        return [job], extra
    if cmd == "sheet":
        job = drop_none({"op": "sheet", "ids": args.ids, "children": args.children, "cols": args.cols, "cell": args.cell, "maxpx": args.maxpx})
        if args.no_labels:
            job["labels"] = False  # drop_none would discard a False
        if args.out:
            extra["out"] = str(Path(args.out).resolve())
        return [job], extra
    if cmd == "image":
        path = Path(args.file).expanduser()
        mime = IMAGE_MIMES.get(path.suffix.lower())
        if not mime:
            raise ValueError("Figma accepts PNG, JPG or GIF images. Convert the file first.")
        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(f"Image is {len(data) >> 20} MB; the limit is {MAX_IMAGE_BYTES >> 20} MB. Downscale it first.")
        job = drop_none({"op": "image", "b64": base64.b64encode(data).decode("ascii"), "fill": args.fill, "parent": args.parent, "w": args.w, "mode": args.mode.upper(), "name": args.name or path.stem})
        if args.at:
            job["at"] = [float(v) for v in args.at.split(",")]
        return [job], extra
    if cmd == "checkpoint":
        return [drop_none({"op": "checkpoint", "title": args.title, "note": args.note})], extra
    if cmd == "eval":
        text = read_text(args)
        return [{"op": "eval", "code": text}], extra
    raise ValueError(f"unhandled command {cmd}")


# --------------------------------------------------------------------------- running


def add_pending_hint(res, args):
    """If a plugin window is waiting for approval, say exactly how to approve it."""
    if res.get("code") not in ("PLUGIN_NOT_CONNECTED", "TIMEOUT"):
        return res
    try:
        waiting = pb.admin(APP, SESSION, "/status", port=args.port, method="GET").get("pending")
    except (pb.BridgeError, urllib.error.URLError, OSError):
        return res
    if waiting:
        res = dict(res, pending=waiting, hint="A Flue Bridge window is waiting for approval. Run `figma_bridge.py pair --approve` (add --file NAME if several), then retry.")
    return res


def run_jobs(jobs, args, extra):
    results = []
    for index, job in enumerate(jobs):
        res = pb.run_job(
            APP, SESSION, job,
            port=args.port, timeout=args.timeout, client=args.target, max_chars=args.max_chars, out=extra.get("out"),
        )
        if not res.get("ok", False):
            res = add_pending_hint(res, args)
            if len(jobs) == 1:
                return fail(res)
            return fail({"ok": False, "failedAt": index, "results": results, "failure": res})
        results.append(res)
    if len(results) == 1:
        return ok(results[0])
    for r in results:
        r.pop("ok", None)
    return ok({"ok": True, "results": results})


def cmd_manifest(args):
    manifest_path = PLUGIN_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["networkAccess"]["devAllowedDomains"] = [f"http://localhost:{args.port}"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    ui_path = PLUGIN_DIR / "ui.html"
    ui = ui_path.read_text(encoding="utf-8")
    new_ui, count = re.subn(r"const PORT = \d+;", f"const PORT = {args.port};", ui, count=1)
    if count != 1:
        return fail({"ok": False, "error": "could not find `const PORT = ...;` in ui.html"})
    ui_path.write_text(new_ui, encoding="utf-8")
    return ok({
        "ok": True,
        "port": args.port,
        "manifest": str(manifest_path),
        "next": f"Stop the old daemon (figma_bridge.py stop), set FLUE_FIGMA_PORT={args.port} (or pass --port {args.port}), "
                "then re-import the plugin in Figma: Plugins > Development > Import plugin from manifest.",
    })


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] in COMMANDS:
            args = build_parser().parse_args(argv)
            if args.cmd == "manifest":
                return cmd_manifest(args)
            if args.cmd == "pair":
                if args.code:
                    res = pb.admin(APP, SESSION, "/pairing", port=args.port)
                    if res.get("ok"):
                        res["next"] = "In Figma: Plugins > Development > Flue Bridge, click the dot to expand the window, enter this code. It works once and expires."
                    return ok(res) if res.get("ok") else fail(res)
                # Default: approve the plugin that is waiting; if none is, say how to get it there.
                res = pb.admin(APP, SESSION, "/approve", port=args.port, body=drop_none({"file": args.file}))
                if res.get("ok"):
                    res["next"] = "Approved. The plugin window should turn green within a second; try `ctx`."
                    return ok(res)
                if res.get("code") == "NO_PENDING":
                    res["hint"] = "Ask the user to open Plugins > Development > Flue Bridge in the file; the window then waits for approval. Run this again."
                return fail(res)
            if args.cmd == "status":
                res = pb.admin(APP, SESSION, "/status", port=args.port, method="GET")
                if res.get("ok"):
                    res["plugin"] = "connected" if res.get("clients") else "not connected"
                    if res.get("pending") and not res.get("clients"):
                        res["hint"] = "A plugin window is waiting for approval: run `figma_bridge.py pair --approve`."
                    elif not res.get("clients"):
                        res["hint"] = pb.NOT_CONNECTED_HINT
                return ok(res) if res.get("ok") else fail(res)
            if args.cmd == "stop":
                return ok(pb.stop_daemon(APP, SESSION, port=args.port))
            jobs, extra = jobs_from_args(args)
            return run_jobs(jobs, args, extra)
        if argv and argv[0] in ("-h", "--help"):
            build_parser().print_help()
            return 0
        args = legacy_parser().parse_args(argv)
        if not (args.stdin or args.file or args.code):
            build_parser().print_help()
            return 2
        return run_jobs(jobs_from_text(read_text(args)), args, {})
    except pb.BridgeError as exc:
        return fail(exc.body())
    except (urllib.error.URLError, ConnectionError) as exc:
        return fail({"ok": False, "code": "DAEMON_UNREACHABLE", "error": f"Cannot reach the bridge daemon: {exc}"})
    except (ValueError, OSError) as exc:
        return fail({"ok": False, "code": "BAD_INPUT", "error": str(exc)})


if __name__ == "__main__":
    raise SystemExit(main())

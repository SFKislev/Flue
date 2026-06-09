import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def default_session_file(session_name):
    """Return the user-scoped session file used by local HTTP bridge panels."""
    return os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"),
        "creative-adapters",
        f"{session_name}.json",
    )


def read_code(args, script_name):
    if args.stdin:
        return sys.stdin.read()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            return handle.read()
    if args.code:
        return args.code
    raise ValueError(f"No {script_name} provided. Use --stdin, --file, or a code argument.")


def read_session_file(session_file):
    with open(session_file, "r", encoding="utf-8-sig") as handle:
        session = json.load(handle)
    url = session.get("url")
    token = session.get("token")
    if not url or not token:
        raise ValueError(f"Bridge session file is incomplete: {session_file}")
    return url, token


def run_bridge(*, app_name, session_name, script_name="ExtendScript", recovery_hint=None):
    session_file = default_session_file(session_name)
    parser = argparse.ArgumentParser(
        description=f"Run {script_name} in {app_name} through the local HTTP bridge."
    )
    parser.add_argument("code", nargs="?", help=f"{script_name} code to execute.")
    parser.add_argument("--stdin", action="store_true", help=f"Read {script_name} from stdin.")
    parser.add_argument("--file", help=f"Read {script_name} from a file.")
    parser.add_argument("--url", help="Bridge eval URL. Defaults to the hidden session file URL.")
    parser.add_argument("--token", help="Bridge token override. Defaults to the hidden session file token.")
    parser.add_argument(
        "--session-file",
        default=session_file,
        help=f"Bridge session file. Defaults to {session_file}.",
    )
    args = parser.parse_args()

    try:
        code = read_code(args, script_name)
        if not code.strip():
            raise ValueError(f"{script_name} input is empty.")

        url = args.url
        token = args.token
        if not url or not token:
            session_url, session_token = read_session_file(args.session_file)
            url = url or session_url
            token = token or session_token
        if not url:
            raise ValueError(
                f"No {app_name} bridge URL is available. Open the Creative "
                "Adapter Bridge panel and retry."
            )
        if not token:
            raise ValueError(
                f"No {app_name} bridge token is available. Open the Creative "
                "Adapter Bridge panel and retry."
            )

        payload = json.dumps({"script": code}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Bridge-Token": token,
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
            return 0
    except FileNotFoundError:
        hint = recovery_hint or "Open the app and enable/open its Creative Adapter Bridge."
        error = (
            f"{app_name} bridge session file was not found. {hint} Then retry."
        )
        print(
            json.dumps({"ok": False, "error": error, "sessionFile": args.session_file}),
            file=sys.stderr,
        )
        return 1
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{app_name} bridge returned HTTP {exc.code}",
                    "detail": detail,
                }
            ),
            file=sys.stderr,
        )
        return 1
    except urllib.error.URLError as exc:
        hint = recovery_hint or "Open the app and enable/open its Creative Adapter Bridge."
        error = (
            f"{app_name} local bridge is not reachable. {hint} Then retry."
        )
        print(json.dumps({"ok": False, "error": error, "detail": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

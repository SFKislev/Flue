import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def norm_path(value):
    return str(value).replace("\\", "/").lower()


def discover_bridge_paths():
    """Discover bridge scripts that are safe for this cleanup tool to match."""
    paths = []
    for path in ROOT.glob("adapters/*_adapter/*_bridge.py"):
        paths.append(path)
    for path in ROOT.glob("*_bridge.py"):
        paths.append(path)
    return sorted(paths)


def adapter_from_path(path):
    parts = path.parts
    for part in parts:
        if part.endswith("_adapter"):
            return part[: -len("_adapter")]
    name = path.stem
    if name.endswith("_bridge"):
        return name[: -len("_bridge")]
    return name


def known_bridges():
    bridges = []
    for path in discover_bridge_paths():
        rel = path.relative_to(ROOT)
        bridges.append(
            {
                "adapter": adapter_from_path(rel),
                "rel": norm_path(rel),
                "abs": norm_path(path),
            }
        )
    return bridges


def parse_windows_cim_date(value):
    if not value:
        return None
    # Example: 20260418143928.123456+180
    raw = str(value)
    try:
        base = raw.split(".")[0]
        return datetime.strptime(base, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def list_windows_processes():
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_Process -Filter \"name = 'python.exe' OR name = 'pythonw.exe'\" "
            "| Select-Object ProcessId,Name,CommandLine,CreationDate "
            "| ConvertTo-Json -Compress"
        ),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "PowerShell process listing failed")
    text = proc.stdout.strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    processes = []
    for item in data:
        processes.append(
            {
                "pid": int(item.get("ProcessId")),
                "name": item.get("Name") or "",
                "commandLine": item.get("CommandLine") or "",
                "startedAt": parse_windows_cim_date(item.get("CreationDate")),
            }
        )
    return processes


def list_posix_processes():
    proc = subprocess.run(
        ["ps", "-eo", "pid=,comm=,lstart=,args="],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ps process listing failed")
    processes = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, name = int(parts[0]), parts[1]
        date_text = " ".join(parts[2:7])
        args = parts[7]
        if "python" not in name.lower() and "python" not in args.lower():
            continue
        started = None
        try:
            started = datetime.strptime(date_text, "%a %b %d %H:%M:%S %Y").replace(
                tzinfo=timezone.utc
            )
        except Exception:
            pass
        processes.append(
            {"pid": pid, "name": name, "commandLine": args, "startedAt": started}
        )
    return processes


def list_python_processes():
    if os.name == "nt":
        return list_windows_processes()
    return list_posix_processes()


def match_bridge(command_line, bridges):
    normalized = norm_path(command_line)
    for bridge in bridges:
        if bridge["rel"] in normalized or bridge["abs"] in normalized:
            return bridge
    return None


def age_seconds(started_at):
    if not started_at:
        return None
    return max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))


def bridge_processes(adapter=None):
    bridges = known_bridges()
    matches = []
    current_pid = os.getpid()
    for proc in list_python_processes():
        if proc["pid"] == current_pid:
            continue
        bridge = match_bridge(proc["commandLine"], bridges)
        if not bridge:
            continue
        if adapter and bridge["adapter"].lower() != adapter.lower():
            continue
        age = age_seconds(proc["startedAt"])
        matches.append(
            {
                "pid": proc["pid"],
                "name": proc["name"],
                "adapter": bridge["adapter"],
                "bridge": bridge["rel"],
                "ageSeconds": age,
                "commandLine": proc["commandLine"],
            }
        )
    return sorted(matches, key=lambda item: (item["adapter"], item["pid"]))


def kill_process(pid):
    if os.name == "nt":
        proc = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    try:
        os.kill(pid, signal.SIGTERM)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List or stop Python processes running Creative Adapter bridge scripts."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List matching bridge processes. This is the default when --kill is omitted.",
    )
    parser.add_argument(
        "--kill",
        choices=["stale", "all"],
        help="Stop matching bridge processes. 'stale' uses --older-than; 'all' stops every match.",
    )
    parser.add_argument(
        "--app",
        help="Limit matches to one adapter name, for example indesign, blender, or photoshop.",
    )
    parser.add_argument(
        "--older-than",
        type=int,
        default=60,
        help="Minimum process age in seconds for --kill stale. Defaults to 60.",
    )
    args = parser.parse_args(argv)

    try:
        matches = bridge_processes(adapter=args.app)
        killed = []
        errors = []
        if args.kill:
            for match in matches:
                should_kill = args.kill == "all"
                if args.kill == "stale":
                    age = match["ageSeconds"]
                    should_kill = age is None or age >= args.older_than
                if not should_kill:
                    continue
                ok, detail = kill_process(match["pid"])
                payload = {k: match[k] for k in ("pid", "adapter", "bridge", "ageSeconds")}
                payload["detail"] = detail
                if ok:
                    killed.append(payload)
                else:
                    errors.append(payload)
        print(
            json.dumps(
                {
                    "ok": not errors,
                    "matches": matches,
                    "killed": killed,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if errors else 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ALIASES = {
    "3dsmax": "3dsmax",
    "3ds-max": "3dsmax",
    "max": "3dsmax",
    "aftereffects": "after_effects",
    "after-effects": "after_effects",
    "ae": "after_effects",
    "audition": "audition",
    "blender": "blender",
    "excel": "excel",
    "figma": "figma",
    "houdini": "houdini",
    "illustrator": "illustrator",
    "indesign": "indesign",
    "photoshop": "photoshop",
    "powerpoint": "powerpoint",
    "premiere": "premiere",
    "premierepro": "premiere",
    "premiere-pro": "premiere",
    "unity": "unity",
    "word": "word",
}

BRIDGES = {
    "3dsmax": "3dsmax_bridge.py",
    "after_effects": "after_effects_bridge.py",
    "audition": "audition_bridge.py",
    "blender": "blender_bridge.py",
    "excel": "excel_bridge.py",
    "figma": "figma_bridge.py",
    "houdini": "houdini_bridge.py",
    "illustrator": "illustrator_bridge.py",
    "indesign": "indesign_bridge.py",
    "photoshop": "photoshop_bridge.py",
    "powerpoint": "powerpoint_bridge.py",
    "premiere": "premiere_bridge.py",
    "unity": "unity_bridge.py",
    "word": "word_bridge.py",
}

PROCESS_NAMES = {
    "3dsmax": "3dsmax.exe",
    "blender": "blender.exe",
    "excel": "EXCEL.EXE",
    "houdini": "houdini.exe",
    "illustrator": "Illustrator.exe",
    "indesign": "InDesign.exe",
    "photoshop": "Photoshop.exe",
    "powerpoint": "POWERPNT.EXE",
    "premiere": "Adobe Premiere Pro.exe",
    "word": "WINWORD.EXE",
}

CONTEXT_EXAMPLES = {
    "3dsmax": "context.py",
    "after_effects": "context.jsx",
    "audition": "context.jsx",
    "blender": "context.py",
    "excel": "context.py",
    "figma": "context.json",
    "houdini": "context.py",
    "illustrator": "context.jsx",
    "indesign": "context.jsx",
    "photoshop": "context.jsx",
    "powerpoint": "context.py",
    "premiere": "context.jsx",
    "unity": "context.json",
    "word": "context.py",
}

AGENT_DOC_TARGETS = ("codex", "claude", "gemini", "antigravity", "qwen", "cursor", "cline", "kilo", "hermes", "opencode", "openclaw", "copilot", "generic", "all")

HARNESS_CONFIGS = {
    "codex": {
        "commands": ["codex"],
        "config_dir": Path(".codex"),
        "global_targets": [
            Path(".codex") / "skills" / "flue" / "SKILL.md",
            Path(".codex") / "AGENTS.md",
        ],
    },
    "claude": {
        "commands": ["claude"],
        "config_dir": Path(".claude"),
        "global_targets": [
            Path(".claude") / "CLAUDE.md",
            Path(".claude") / "skills" / "flue" / "SKILL.md",
        ],
    },
    "gemini": {
        "commands": ["gemini"],
        "config_dir": Path(".gemini"),
        "global_targets": [
            Path(".gemini") / "GEMINI.md",
            Path(".gemini") / "flue.md",
        ],
    },
    "antigravity": {
        "commands": ["antigravity"],
        "config_dir": Path(".antigravity"),
        "global_targets": [
            Path(".antigravity") / "skills" / "flue" / "SKILL.md",
            Path(".antigravity") / "AGENTS.md",
        ],
    },
    "qwen": {
        "commands": ["qwen"],
        "config_dir": Path(".qwen"),
        "global_targets": [
            Path(".qwen") / "QWEN.md",
            Path(".qwen") / "flue.md",
        ],
    },
    "cursor": {
        "commands": ["cursor"],
        "config_dir": Path(".cursor"),
        "global_targets": [
            Path(".cursor") / "skills" / "flue" / "SKILL.md",
        ],
    },
    "cline": {
        "commands": ["cline"],
        "config_dir": Path(".cline"),
        "global_targets": [
            Path(".cline") / "skills" / "flue" / "SKILL.md",
        ],
    },
    "kilo": {
        "commands": ["kilo"],
        "config_dir": Path(".kilo"),
        "global_targets": [
            Path(".kilo") / "skills" / "flue" / "SKILL.md",
        ],
    },
    "hermes": {
        "commands": [],
        "config_dir": Path(".hermes"),
        "global_targets": [
            Path(".hermes") / "skills" / "flue" / "SKILL.md",
        ],
    },
    "opencode": {
        "commands": ["opencode"],
        "config_dir": Path(".config") / "opencode",
        "global_targets": [
            Path(".config") / "opencode" / "agents" / "flue.md",
        ],
    },
    "openclaw": {
        "commands": ["openclaw"],
        "config_dir": Path(".openclaw"),
        "global_targets": [
            Path(".openclaw") / "skills" / "flue" / "SKILL.md",
        ],
    },
    "copilot": {
        "commands": [],
        "config_dir": Path(".copilot"),
        "global_targets": [
            Path(".copilot") / "skills" / "flue" / "SKILL.md",
            Path(".copilot") / "instructions" / "flue.instructions.md",
            Path(".copilot") / "copilot-instructions.md",
        ],
    },
}


def adapter_name(value):
    key = value.lower().replace("_", "-")
    try:
        return ALIASES[key]
    except KeyError:
        choices = ", ".join(sorted(set(ALIASES)))
        raise argparse.ArgumentTypeError(f"unknown adapter '{value}'. Choices: {choices}")


def adapter_dir(name):
    path = ROOT / "adapters" / f"{name}_adapter"
    if not path.exists():
        raise FileNotFoundError(f"Adapter directory not found: {path}")
    return path


def bridge_path(name):
    path = adapter_dir(name) / BRIDGES[name]
    if not path.exists():
        raise FileNotFoundError(f"Bridge script not found: {path}")
    return path


def run_process(args, *, input_text=None):
    proc = subprocess.run(
        args,
        cwd=str(ROOT),
        input=input_text,
        text=True,
        check=False,
    )
    return proc.returncode


def run_external_process(args, *, cwd=None):
    proc = subprocess.run(
        args,
        cwd=str(cwd or Path.home()),
        text=True,
        check=False,
    )
    return proc.returncode


def start_external_process(args, *, cwd=None, new_console=False):
    creationflags = 0
    if os.name == "nt":
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if new_console:
            creationflags |= subprocess.CREATE_NEW_CONSOLE
    proc = subprocess.Popen(
        args,
        cwd=str(cwd or Path.home()),
        text=True,
        creationflags=creationflags,
    )
    return proc.pid


def installed_flue_version():
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "show", "flue"],
        cwd=str(Path.home()),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
                if version:
                    return version

    try:
        return importlib.metadata.version("flue")
    except importlib.metadata.PackageNotFoundError:
        return None


def latest_pypi_flue_version():
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/flue/json", timeout=10) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    info = payload.get("info") or {}
    version = info.get("version")
    return version.strip() if isinstance(version, str) and version.strip() else None


def running_from_windows_flue_exe():
    if os.name != "nt":
        return False
    if Path(sys.argv[0]).name.lower() in {"flue", "flue.exe"}:
        return True

    try:
        import ctypes

        ctypes.windll.kernel32.GetCommandLineW.restype = ctypes.c_wchar_p
        command_line = (ctypes.windll.kernel32.GetCommandLineW() or "").lstrip()
    except Exception:
        return False

    if command_line.startswith('"'):
        executable = command_line.split('"', 2)[1]
    else:
        executable = command_line.split(maxsplit=1)[0] if command_line else ""
    return (
        Path(executable).name.lower() == "flue.exe"
        or "\\flue.exe" in command_line.lower()
        or "/flue.exe" in command_line.lower()
    )


def normalize_path_key(path):
    text = str(path)
    return text.lower() if os.name == "nt" else text


def unique_paths(paths):
    seen = set()
    result = []
    for path in paths:
        key = normalize_path_key(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def home_candidates():
    candidates = [Path.home()]
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile))

    if os.name == "nt":
        username = os.environ.get("USERNAME")
        if username:
            candidates.append(Path("C:/Users") / username)
        homedrive = os.environ.get("HOMEDRIVE")
        homepath = os.environ.get("HOMEPATH")
        if homedrive and homepath:
            candidates.append(Path(homedrive + homepath))

    result = []
    for index, path in enumerate(unique_paths(candidates)):
        if index == 0 or path.exists():
            result.append(path)
    return result


def scripts_dir():
    executable_dir = Path(sys.executable).resolve().parent
    if os.name != "nt":
        return executable_dir
    if executable_dir.name.lower() == "scripts":
        return executable_dir
    return executable_dir / "Scripts"


def path_entries():
    return [Path(item) for item in os.environ.get("PATH", "").split(os.pathsep) if item]


def is_scripts_dir_on_path():
    scripts = normalize_path_key(scripts_dir())
    return any(normalize_path_key(path) == scripts for path in path_entries())


def installed_command(name):
    return shutil.which(name)


def vscode_copilot_installed():
    homes = home_candidates()
    for home in homes:
        for base in (home / ".vscode" / "extensions", home / ".vscode-insiders" / "extensions"):
            if not base.exists():
                continue
            if any(base.glob("github.copilot-*")) and any(base.glob("github.copilot-chat-*")):
                return True
    return False


def module_command():
    return [sys.executable, "-m", "flue.cli"]


def format_command_for_display(parts):
    return subprocess.list2cmdline([str(part) for part in parts])


def powershell_command_literal(parts):
    quoted = []
    for part in parts:
        text = str(part).replace("'", "''")
        quoted.append(f"'{text}'")
    return "& " + " ".join(quoted)


def packaged_skill_source():
    candidates = [
        ROOT / "skill.md",
        ROOT / "flue" / "skill.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Flue skill source not found.")


def packaged_known_issues_source():
    candidates = [
        ROOT / "docs" / "known-issues.md",
        ROOT / "flue" / "known-issues.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Flue known-issues source not found.")


def packaged_setup_source():
    candidates = [
        ROOT / "docs" / "setup.md",
        ROOT / "flue" / "setup.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Flue setup source not found.")


def flue_install_info():
    return {
        "root": str(ROOT),
        "pythonExecutable": str(Path(sys.executable).resolve()),
        "scriptsDir": str(scripts_dir()),
        "docsPath": str(packaged_skill_source()),
        "flueCommandPath": installed_command("flue"),
        "flueOnPath": installed_command("flue") is not None,
        "scriptsDirOnPath": is_scripts_dir_on_path(),
        "preferredCommand": "flue" if installed_command("flue") else format_command_for_display(module_command()),
        "fallbackCommand": format_command_for_display(module_command()),
        "homeCandidates": [str(path) for path in home_candidates()],
        "PATH": [str(p) for p in path_entries()],
    }


def cmd_where(_args):
    info = flue_install_info()
    if getattr(_args, "json", False):
        print(json.dumps(info, indent=2))
        return 0

    root = Path(info["root"])
    folders = []
    for name in ("adapters", "bridges", "flue", "shared", "tools"):
        path = root / name
        if path.exists():
            folders.append(name)

    print(str(root))
    if folders:
        print("")
        print("Folders:")
        for name in folders:
            print(f"  {name}/")
    return 0


def cmd_software(_args):
    for name in sorted(BRIDGES):
        print(name)
    return 0


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    print(path)
    return True


def copy_file(source, target, *, force):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        print(f"File already exists: {target}. Use --force to replace it.", file=sys.stderr)
        return False
    shutil.copy2(source, target)
    print(target)
    return True


def copy_dir(source, target, *, force):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not force:
            print(f"Directory already exists: {target}. Use --force to replace it.", file=sys.stderr)
            return False
        shutil.rmtree(target)
    shutil.copytree(source, target)
    print(target)
    return True


def remove_file(path):
    if not path.exists():
        return False
    path.unlink()
    print(path)
    return True


def remove_dir(path):
    if not path.exists():
        return False
    shutil.rmtree(path)
    print(path)
    return True


def upsert_marked_block(path, begin, end, block):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    if begin in content and end in content:
        start = content.index(begin)
        finish = content.index(end, start) + len(end)
        content = content[:start] + block + content[finish:]
    else:
        separator = "\n\n" if content.strip() else ""
        content = content.rstrip() + separator + block
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def remove_marked_block(path, begin, end):
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    if begin not in content or end not in content:
        return False
    start = content.index(begin)
    finish = content.index(end, start) + len(end)
    new_content = (content[:start] + content[finish:]).strip()
    if new_content:
        path.write_text(new_content + "\n", encoding="utf-8")
        print(path)
    else:
        path.unlink()
        print(path)
    return True


def remove_if_matches(path, source):
    if not path.exists():
        return False
    if path.read_text(encoding="utf-8") != source.read_text(encoding="utf-8"):
        print(f"Skipping modified file: {path}", file=sys.stderr)
        return False
    path.unlink()
    print(path)
    return True


def adapter_docs_sources():
    items = []
    for adapter_path in sorted((ROOT / "adapters").glob("*_adapter")):
        if adapter_path.name.startswith("~"):
            continue
        app_md = adapter_path / "APP.md"
        if not app_md.exists():
            continue
        name = adapter_path.name.removesuffix("_adapter")
        adapter_files = [("APP.md", app_md)]
        api_index = adapter_path / "docs" / "api-index.txt"
        if api_index.exists():
            adapter_files.append(("docs/api-index.txt", api_index))
        items.append((name, adapter_files))
    return items


def pointer_note_text(relative_entry):
    return f"""# Flue

If asked to perform a task in a desktop application, use Flue: a Python
package installed on this machine that lets agents inspect and edit supported
apps through their scripting APIs.

Read `{relative_entry}` first.
"""


def copilot_instruction_text():
    return """---
applyTo: "**"
---

When asked to operate supported desktop software on this machine, use the
Flue skill from `~/.copilot/skills/flue/SKILL.md`.
"""


def copilot_cli_instruction_text():
    return """When asked to operate supported desktop software on this machine, use the Flue skill from `~/.copilot/skills/flue/SKILL.md`."""


def installed_skill_text(description):
    body = packaged_skill_source().read_text(encoding="utf-8").rstrip()
    return f"""---
name: flue
description: {description}
---

{body}
"""


def install_local_docs_bundle(bundle_dir, *, entry_filename, entry_text, force):
    ok = True
    if bundle_dir.exists():
        if not force:
            print(f"Directory already exists: {bundle_dir}. Use --force to replace it.", file=sys.stderr)
            return False
        for stale_file in ("SKILL.md", "INDEX.md", "AGENTS.md", "common.md"):
            stale_path = bundle_dir / stale_file
            if stale_file != entry_filename:
                remove_file(stale_path)
        remove_dir(bundle_dir / "shared")
        remove_dir(bundle_dir / "docs")
        remove_dir(bundle_dir / "adapters")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    ok = write_text(bundle_dir / entry_filename, entry_text) and ok

    shared_dir = bundle_dir / "shared"
    ok = copy_file(ROOT / "shared" / "coexistence.md", shared_dir / "coexistence.md", force=True) and ok
    ok = copy_file(ROOT / "shared" / "bridge-contract.md", shared_dir / "bridge-contract.md", force=True) and ok

    docs_dir = bundle_dir / "docs"
    ok = copy_file(packaged_known_issues_source(), docs_dir / "known-issues.md", force=True) and ok
    ok = copy_file(packaged_setup_source(), docs_dir / "setup.md", force=True) and ok

    adapters_dir = bundle_dir / "adapters"
    for name, files in adapter_docs_sources():
        for relative_path, source in files:
            ok = copy_file(source, adapters_dir / name / relative_path, force=True) and ok
    return ok


def flue_pointer_block(entry_path):
    begin = "<!-- FLUE START -->"
    end = "<!-- FLUE END -->"
    block = (
        f"{begin}\n"
        "# Flue\n\n"
        "Flue is installed on this machine. It lets agents communicate with "
        "supported desktop software directly through local scripting bridges, "
        "without MCP servers.\n\n"
        "When requested to operate supported desktop software, read:\n\n"
        f"`{entry_path}`\n"
        f"{end}"
    )
    return begin, end, block


def flue_and_legacy_pointer_markers():
    return (
        ("<!-- FLUE START -->", "<!-- FLUE END -->"),
        ("<!-- SOFTWIRE START -->", "<!-- SOFTWIRE END -->"),
    )


def remove_flue_and_legacy_pointer_blocks(path):
    removed = False
    for begin, end in flue_and_legacy_pointer_markers():
        removed = remove_marked_block(path, begin, end) or removed
    return removed


def remove_named_dirs(parent, names):
    removed = False
    for name in names:
        removed = remove_dir(parent / name) or removed
    return removed


def remove_named_markdown_files(parent, names):
    removed = False
    for name in names:
        removed = remove_file(parent / f"{name}.md") or removed
    return removed


def cmd_docs(_args):
    print(packaged_skill_source())
    return 0


def agents_report():
    homes = home_candidates()
    report = []
    for name, config in HARNESS_CONFIGS.items():
        commands = []
        for command in config["commands"]:
            commands.append({"name": command, "path": installed_command(command)})

        config_dirs = []
        targets = []
        for home in homes:
            config_dir = home / config["config_dir"]
            config_dirs.append({"home": str(home), "path": str(config_dir), "exists": config_dir.exists()})
            for target in config["global_targets"]:
                path = home / target
                targets.append({"home": str(home), "path": str(path), "exists": path.exists()})

        command_on_path = any(item["path"] for item in commands)
        detection_reasons = []
        if command_on_path:
            detection_reasons.append("command")
        if name == "copilot" and vscode_copilot_installed():
            detection_reasons.append("vscode_extension")
        if any(item["exists"] for item in config_dirs):
            detection_reasons.append("config_dir")

        detected = bool(detection_reasons)
        report.append(
            {
                "harness": name,
                "commandOnPath": command_on_path,
                "commands": commands,
                "homes": [str(home) for home in homes],
                "configDir": config_dirs[0]["path"],
                "configDirExists": config_dirs[0]["exists"],
                "configDirs": config_dirs,
                "detectionReasons": detection_reasons,
                "detected": detected,
                "globalTargets": targets,
            }
        )
    return report


def detect_agent_targets():
    targets = []
    for item in agents_report():
        if item["detected"]:
            targets.append(item["harness"])
    return targets


def cmd_agents(_args):
    if getattr(_args, "json", False):
        print(json.dumps(agents_report(), indent=2))
        return 0

    rows = []
    for item in agents_report():
        status = "yes" if item["detected"] else "no"
        targets = []
        for target in item["globalTargets"]:
            if target["exists"]:
                targets.append(target["path"])
        target_text = "; ".join(targets) if targets else "-"
        rows.append(
            {
                "Harness": item["harness"],
                "Detected": status,
                "Targets": target_text,
            }
        )

    headers = ["Harness", "Detected", "Targets"]
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(row[header]))

    header_line = "  ".join(header.ljust(widths[header]) for header in headers)
    divider = "  ".join("-" * widths[header] for header in headers)
    print(header_line)
    print(divider)
    for row in rows:
        print("  ".join(row[header].ljust(widths[header]) for header in headers))
    return 0


def install_codex_docs(args):
    ok = True
    if args.path:
            bundle_dir = Path(args.path).expanduser() / "flue"
            ok = install_local_docs_bundle(
                bundle_dir,
                entry_filename="SKILL.md",
                entry_text=installed_skill_text(
                    "Use when Codex needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
                ),
                force=args.force,
        ) and ok
    else:
        for home in home_candidates():
            bundle_dir = home / ".codex" / "skills" / "flue"
            ok = install_local_docs_bundle(
                bundle_dir,
                entry_filename="SKILL.md",
                entry_text=installed_skill_text(
                    "Use when Codex needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
                ),
                force=args.force,
            ) and ok
            begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
            agents = home / ".codex" / "AGENTS.md"
            upsert_marked_block(agents, begin, end, block)
            print(agents)
    return ok


def install_claude_docs(args):
    ok = True
    if args.path:
        target_root = Path(args.path).expanduser()
        bundle_dir = target_root / "skills" / "flue"
        ok = install_local_docs_bundle(
            bundle_dir,
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Claude needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
        remove_file(target_root / "flue.md")
        begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
        memory = target_root / "CLAUDE.md"
        upsert_marked_block(memory, begin, end, block)
        print(memory)
    else:
        for home in home_candidates():
            target_root = home / ".claude"
            bundle_dir = target_root / "skills" / "flue"
            ok = install_local_docs_bundle(
                bundle_dir,
                entry_filename="SKILL.md",
                entry_text=installed_skill_text(
                    "Use when Claude needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
                ),
                force=args.force,
            ) and ok
            remove_file(target_root / "flue.md")
            begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
            memory = target_root / "CLAUDE.md"
            upsert_marked_block(memory, begin, end, block)
            print(memory)
    return ok


def install_gemini_docs(args):
    ok = True
    if args.path:
        target_root = Path(args.path).expanduser()
        bundle_dir = target_root / "flue"
        ok = install_local_docs_bundle(
            bundle_dir,
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Gemini needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
        remove_file(target_root / "flue.md")
        begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
        memory = target_root / "GEMINI.md"
        upsert_marked_block(memory, begin, end, block)
        print(memory)
    else:
        for home in home_candidates():
            target_root = home / ".gemini"
            bundle_dir = target_root / "flue"
            ok = install_local_docs_bundle(
                bundle_dir,
                entry_filename="SKILL.md",
                entry_text=installed_skill_text(
                    "Use when Gemini needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
                ),
                force=args.force,
            ) and ok
            remove_file(target_root / "flue.md")
            begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
            memory = target_root / "GEMINI.md"
            upsert_marked_block(memory, begin, end, block)
            print(memory)
    return ok


def install_antigravity_docs(args):
    ok = True
    if args.path:
        bundle_dir = Path(args.path).expanduser() / "flue"
        ok = install_local_docs_bundle(
            bundle_dir,
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Antigravity needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
    else:
        for home in home_candidates():
            bundle_dir = home / ".antigravity" / "skills" / "flue"
            ok = install_local_docs_bundle(
                bundle_dir,
                entry_filename="SKILL.md",
                entry_text=installed_skill_text(
                    "Use when Antigravity needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
                ),
                force=args.force,
            ) and ok
            begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
            agents = home / ".antigravity" / "AGENTS.md"
            upsert_marked_block(agents, begin, end, block)
            print(agents)
    return ok


def install_cursor_docs(args):
    ok = True
    if args.path:
        return install_local_docs_bundle(
            Path(args.path).expanduser() / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Cursor needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        )
    for home in home_candidates():
        ok = install_local_docs_bundle(
            home / ".cursor" / "skills" / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Cursor needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
    return ok


def install_kilo_docs(args):
    ok = True
    if args.path:
        return install_local_docs_bundle(
            Path(args.path).expanduser() / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Kilo needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        )
    for home in home_candidates():
        ok = install_local_docs_bundle(
            home / ".kilo" / "skills" / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Kilo needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
    return ok


def install_hermes_docs(args):
    ok = True
    if args.path:
        return install_local_docs_bundle(
            Path(args.path).expanduser() / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Hermes Agent needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        )
    for home in home_candidates():
        hermes_root = home / ".hermes"
        if not hermes_root.exists():
            continue
        ok = install_local_docs_bundle(
            hermes_root / "skills" / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Hermes Agent needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
    return ok


def install_cline_docs(args):
    ok = True
    if args.path:
        return install_local_docs_bundle(
            Path(args.path).expanduser() / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Cline needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        )
    for home in home_candidates():
        ok = install_local_docs_bundle(
            home / ".cline" / "skills" / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Cline needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
    return ok


def install_qwen_docs(args):
    ok = True
    if args.path:
        target_root = Path(args.path).expanduser()
        bundle_dir = target_root / "flue"
        ok = install_local_docs_bundle(
            bundle_dir,
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when Qwen needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
        remove_file(target_root / "flue.md")
        begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
        memory = target_root / "QWEN.md"
        upsert_marked_block(memory, begin, end, block)
        print(memory)
    else:
        for home in home_candidates():
            target_root = home / ".qwen"
            bundle_dir = target_root / "flue"
            ok = install_local_docs_bundle(
                bundle_dir,
                entry_filename="SKILL.md",
                entry_text=installed_skill_text(
                    "Use when Qwen needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
                ),
                force=args.force,
            ) and ok
            remove_file(target_root / "flue.md")
            begin, end, block = flue_pointer_block(bundle_dir / "SKILL.md")
            memory = target_root / "QWEN.md"
            upsert_marked_block(memory, begin, end, block)
            print(memory)
    return ok


def install_opencode_docs(args):
    ok = True
    if args.path:
        target_root = Path(args.path).expanduser()
        ok = install_local_docs_bundle(
            target_root / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when OpenCode needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
        ok = write_text(target_root / "flue.md", pointer_note_text("flue/SKILL.md")) and ok
        return ok
    for home in home_candidates():
        target_root = home / ".config" / "opencode" / "agents"
        ok = install_local_docs_bundle(
            target_root / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when OpenCode needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
        ok = write_text(target_root / "flue.md", pointer_note_text("flue/SKILL.md")) and ok
    return ok


def install_openclaw_docs(args):
    ok = True
    if args.path:
        return install_local_docs_bundle(
            Path(args.path).expanduser() / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when OpenClaw needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        )
    for home in home_candidates():
        ok = install_local_docs_bundle(
            home / ".openclaw" / "skills" / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when OpenClaw needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
    return ok


def install_copilot_docs(args):
    ok = True
    if args.path:
        target_root = Path(args.path).expanduser()
        bundle_dir = target_root / "skills" / "flue"
        ok = install_local_docs_bundle(
            bundle_dir,
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when GitHub Copilot needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
        ok = write_text(target_root / "instructions" / "flue.instructions.md", copilot_instruction_text()) and ok
        ok = write_text(target_root / "copilot-instructions.md", copilot_cli_instruction_text()) and ok
        return ok
    for home in home_candidates():
        target_root = home / ".copilot"
        ok = install_local_docs_bundle(
            target_root / "skills" / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when GitHub Copilot needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=args.force,
        ) and ok
        ok = write_text(target_root / "instructions" / "flue.instructions.md", copilot_instruction_text()) and ok
        ok = write_text(target_root / "copilot-instructions.md", copilot_cli_instruction_text()) and ok
    return ok


def install_generic_docs(args):
    target = Path(args.path).expanduser() if args.path else Path.cwd() / "AGENTS.md"
    bundle_dir = target.parent / "flue"
    ok = install_local_docs_bundle(
        bundle_dir,
        entry_filename="SKILL.md",
        entry_text=installed_skill_text(
            "Use when an agent needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
        ),
        force=args.force,
    )
    ok = write_text(target, pointer_note_text("flue/SKILL.md")) and ok
    return ok


def install_universal_global_docs(*, force):
    ok = True
    for home in home_candidates():
        ok = install_local_docs_bundle(
            home / ".agents" / "skills" / "flue",
            entry_filename="SKILL.md",
            entry_text=installed_skill_text(
                "Use when an agent needs to inspect, install, test, or run Flue adapters to control supported Windows and macOS desktop apps through local scripting bridges.",
            ),
            force=force,
        ) and ok
    return ok


def uninstall_codex_docs(args):
    removed = False
    if args.path:
        removed = remove_named_dirs(Path(args.path).expanduser(), ("flue", "softwire")) or removed
    else:
        for home in home_candidates():
            removed = remove_named_dirs(home / ".codex" / "skills", ("flue", "softwire")) or removed
            removed = remove_flue_and_legacy_pointer_blocks(home / ".codex" / "AGENTS.md") or removed
    return removed


def uninstall_claude_docs(args):
    removed = False
    if args.path:
        target_root = Path(args.path).expanduser()
        removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
        removed = remove_named_dirs(target_root / "skills", ("flue", "softwire")) or removed
        removed = remove_flue_and_legacy_pointer_blocks(target_root / "CLAUDE.md") or removed
    else:
        for home in home_candidates():
            target_root = home / ".claude"
            removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
            removed = remove_named_dirs(target_root / "skills", ("flue", "softwire")) or removed
            removed = remove_flue_and_legacy_pointer_blocks(target_root / "CLAUDE.md") or removed
    return removed


def uninstall_gemini_docs(args):
    removed = False
    if args.path:
        target_root = Path(args.path).expanduser()
        removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
        removed = remove_named_dirs(target_root, ("flue", "softwire")) or removed
        removed = remove_flue_and_legacy_pointer_blocks(target_root / "GEMINI.md") or removed
    else:
        for home in home_candidates():
            target_root = home / ".gemini"
            removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
            removed = remove_named_dirs(target_root, ("flue", "softwire")) or removed
            removed = remove_flue_and_legacy_pointer_blocks(target_root / "GEMINI.md") or removed
    return removed


def uninstall_antigravity_docs(args):
    removed = False
    if args.path:
        removed = remove_named_dirs(Path(args.path).expanduser(), ("flue", "softwire")) or removed
    else:
        for home in home_candidates():
            removed = remove_named_dirs(home / ".antigravity" / "skills", ("flue", "softwire")) or removed
            removed = remove_flue_and_legacy_pointer_blocks(home / ".antigravity" / "AGENTS.md") or removed
    return removed


def uninstall_cursor_docs(args):
    removed = False
    if args.path:
        return remove_named_dirs(Path(args.path).expanduser(), ("flue", "softwire"))
    for home in home_candidates():
        removed = remove_named_dirs(home / ".cursor" / "skills", ("flue", "softwire")) or removed
    return removed


def uninstall_kilo_docs(args):
    removed = False
    if args.path:
        return remove_named_dirs(Path(args.path).expanduser(), ("flue", "softwire"))
    for home in home_candidates():
        removed = remove_named_dirs(home / ".kilo" / "skills", ("flue", "softwire")) or removed
    return removed


def uninstall_hermes_docs(args):
    removed = False
    if args.path:
        return remove_named_dirs(Path(args.path).expanduser(), ("flue", "softwire"))
    for home in home_candidates():
        removed = remove_named_dirs(home / ".hermes" / "skills", ("flue", "softwire")) or removed
    return removed


def uninstall_cline_docs(args):
    removed = False
    if args.path:
        return remove_named_dirs(Path(args.path).expanduser(), ("flue", "softwire"))
    for home in home_candidates():
        removed = remove_named_dirs(home / ".cline" / "skills", ("flue", "softwire")) or removed
    return removed


def uninstall_qwen_docs(args):
    removed = False
    if args.path:
        target_root = Path(args.path).expanduser()
        removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
        removed = remove_named_dirs(target_root, ("flue", "softwire")) or removed
        removed = remove_flue_and_legacy_pointer_blocks(target_root / "QWEN.md") or removed
    else:
        for home in home_candidates():
            target_root = home / ".qwen"
            removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
            removed = remove_named_dirs(target_root, ("flue", "softwire")) or removed
            removed = remove_flue_and_legacy_pointer_blocks(target_root / "QWEN.md") or removed
    return removed


def uninstall_opencode_docs(args):
    removed = False
    if args.path:
        target_root = Path(args.path).expanduser()
        removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
        removed = remove_named_dirs(target_root, ("flue", "softwire")) or removed
        return removed
    for home in home_candidates():
        target_root = home / ".config" / "opencode" / "agents"
        removed = remove_named_markdown_files(target_root, ("flue", "softwire")) or removed
        removed = remove_named_dirs(target_root, ("flue", "softwire")) or removed
    return removed


def uninstall_openclaw_docs(args):
    removed = False
    if args.path:
        return remove_named_dirs(Path(args.path).expanduser(), ("flue", "softwire"))
    for home in home_candidates():
        removed = remove_named_dirs(home / ".openclaw" / "skills", ("flue", "softwire")) or removed
    return removed


def uninstall_copilot_docs(args):
    removed = False
    if args.path:
        target_root = Path(args.path).expanduser()
        removed = remove_file(target_root / "instructions" / "flue.instructions.md") or removed
        removed = remove_file(target_root / "instructions" / "softwire.instructions.md") or removed
        removed = remove_file(target_root / "copilot-instructions.md") or removed
        removed = remove_named_dirs(target_root / "skills", ("flue", "softwire")) or removed
        return removed
    for home in home_candidates():
        target_root = home / ".copilot"
        removed = remove_file(target_root / "instructions" / "flue.instructions.md") or removed
        removed = remove_file(target_root / "instructions" / "softwire.instructions.md") or removed
        removed = remove_file(target_root / "copilot-instructions.md") or removed
        removed = remove_named_dirs(target_root / "skills", ("flue", "softwire")) or removed
    return removed


def uninstall_generic_docs(args):
    target = Path(args.path).expanduser() if args.path else Path.cwd() / "AGENTS.md"
    removed = remove_file(target) or False
    removed = remove_named_dirs(target.parent, ("flue", "softwire")) or removed
    return removed


def uninstall_universal_global_docs():
    removed = False
    for home in home_candidates():
        removed = remove_named_dirs(home / ".agents" / "skills", ("flue", "softwire")) or removed
    return removed


def cmd_install_agent_docs(args):
    targets = ("codex", "claude", "gemini", "antigravity", "qwen", "cursor", "cline", "kilo", "hermes", "opencode", "openclaw", "copilot", "generic") if args.target == "all" else (args.target,)
    ok = True
    for target in targets:
        if target == "codex":
            ok = install_codex_docs(args) and ok
        elif target == "claude":
            ok = install_claude_docs(args) and ok
        elif target == "gemini":
            ok = install_gemini_docs(args) and ok
        elif target == "antigravity":
            ok = install_antigravity_docs(args) and ok
        elif target == "qwen":
            ok = install_qwen_docs(args) and ok
        elif target == "cursor":
            ok = install_cursor_docs(args) and ok
        elif target == "cline":
            ok = install_cline_docs(args) and ok
        elif target == "kilo":
            ok = install_kilo_docs(args) and ok
        elif target == "hermes":
            ok = install_hermes_docs(args) and ok
        elif target == "opencode":
            ok = install_opencode_docs(args) and ok
        elif target == "openclaw":
            ok = install_openclaw_docs(args) and ok
        elif target == "copilot":
            ok = install_copilot_docs(args) and ok
        elif target == "generic":
            ok = install_generic_docs(args) and ok
    return 0 if ok else 1


def cmd_uninstall(args):
    if args.agent == "auto":
        targets = detect_agent_targets()
        if not targets:
            targets = ["generic"]
    elif args.agent == "all":
        targets = ["codex", "claude", "gemini", "antigravity", "qwen", "cursor", "cline", "kilo", "hermes", "opencode", "openclaw", "copilot", "generic"]
    else:
        targets = [args.agent]

    print("Removing Flue agent instructions for: " + ", ".join(targets))
    removed_any = uninstall_universal_global_docs()
    for target in targets:
        if target == "codex":
            removed_any = uninstall_codex_docs(args) or removed_any
        elif target == "claude":
            removed_any = uninstall_claude_docs(args) or removed_any
        elif target == "gemini":
            removed_any = uninstall_gemini_docs(args) or removed_any
        elif target == "antigravity":
            removed_any = uninstall_antigravity_docs(args) or removed_any
        elif target == "qwen":
            removed_any = uninstall_qwen_docs(args) or removed_any
        elif target == "cursor":
            removed_any = uninstall_cursor_docs(args) or removed_any
        elif target == "cline":
            removed_any = uninstall_cline_docs(args) or removed_any
        elif target == "kilo":
            removed_any = uninstall_kilo_docs(args) or removed_any
        elif target == "hermes":
            removed_any = uninstall_hermes_docs(args) or removed_any
        elif target == "opencode":
            removed_any = uninstall_opencode_docs(args) or removed_any
        elif target == "openclaw":
            removed_any = uninstall_openclaw_docs(args) or removed_any
        elif target == "copilot":
            removed_any = uninstall_copilot_docs(args) or removed_any
        elif target == "generic":
            removed_any = uninstall_generic_docs(args) or removed_any
    return 0 if removed_any else 1


def cmd_setup(args):
    if args.agent == "auto":
        targets = detect_agent_targets()
        if not targets:
            print("No AI harness found. Flue needs a harness in order to work.", file=sys.stderr)
            return 1
        chosen = targets
    elif args.agent == "all":
        chosen = ["codex", "claude", "gemini", "antigravity", "qwen", "cursor", "cline", "kilo", "hermes", "opencode", "openclaw", "copilot"]
    else:
        chosen = [args.agent]

    print("Registering Flue agent instructions for: " + ", ".join(chosen))
    homes = home_candidates()
    if len(homes) > 1:
        print("Detected multiple home directories:")
        for home in homes:
            print(f"  {home}")

    # Setup always refreshes existing Flue skill bundles in place so a
    # bootstrap/base skill install can be upgraded without manual cleanup.
    effective_force = True
    ok = True
    ok = install_universal_global_docs(force=effective_force) and ok
    for target in chosen:
        setup_args = argparse.Namespace(target=target, path=None, force=effective_force)
        ok = (cmd_install_agent_docs(setup_args) == 0) and ok

    info = flue_install_info()
    print("")
    print("Flue is installed. New agent sessions should discover it through the registered global instructions.")
    print(f"Use Flue with: {info['preferredCommand']}")
    if not info["flueOnPath"]:
        print("The 'flue' command is not on PATH in this shell. Agents should use the Python module fallback.")
        print(f"Fallback command: {info['fallbackCommand']}")
    elif not info["scriptsDirOnPath"]:
        print("Warning: the current Python Scripts directory is not on PATH for this shell session.")
        print(f"Fallback command: {info['fallbackCommand']}")
    print("Verify the bridge runtime with: " + info["preferredCommand"] + " adapters")
    return 0 if ok else 1


def cmd_update(args):
    if args.docs_only and args.package_only:
        print("--docs-only and --package-only cannot be used together.", file=sys.stderr)
        return 1

    if running_from_windows_flue_exe() and not args.docs_only:
        relaunch = [sys.executable, "-m", "flue.cli", "update"]
        if args.agent != "auto":
            relaunch += ["--agent", args.agent]
        if args.package_only:
            relaunch.append("--package-only")
        if args.force_docs:
            relaunch.append("--force-docs")
        print("Relaunching via Python module so pip can replace flue.exe...")
        start_external_process(relaunch, new_console=True)
        print("Update continues in a new window. This launcher will now exit.")
        return 0

    before_version = installed_flue_version()
    if not args.docs_only:
        latest_version = latest_pypi_flue_version()
        if before_version and latest_version and before_version == latest_version and not args.force_docs:
            print(f"Flue is already up to date ({before_version}).")
            return 0
        if before_version:
            print(f"Current Flue version: {before_version}")
        print("Updating the Flue Python package with pip...")
        pip_command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-cache-dir",
            "flue",
        ]
        rc = run_external_process(pip_command)
        if rc != 0:
            return rc

    if args.package_only:
        return 0

    after_version = installed_flue_version()
    print("")
    if args.docs_only:
        print("Refreshing Flue agent documentation...")
    elif before_version and after_version and before_version == after_version:
        print(f"Flue is already up to date ({after_version or 'unknown version'}). Refreshing agent documentation...")
    else:
        print(f"Flue changed from {before_version or 'unknown'} to {after_version or 'unknown'}. Refreshing agent documentation...")
    setup_command = [
        sys.executable,
        "-m",
        "flue.cli",
        "setup",
        "--force",
        "--agent",
        args.agent,
    ]
    return run_external_process(setup_command)


def cmd_test(args):
    name = args.adapter
    context = adapter_dir(name) / "examples" / CONTEXT_EXAMPLES[name]
    if not context.exists():
        raise FileNotFoundError(f"Context example not found: {context}")
    return run_process(
        [sys.executable, str(bridge_path(name)), "--stdin"],
        input_text=context.read_text(encoding="utf-8-sig"),
    )


def cmd_modal(args):
    if os.name != "nt":
        print("Modal window inspection is currently Windows-only.", file=sys.stderr)
        return 1

    process_name = PROCESS_NAMES.get(args.adapter)
    if not process_name:
        print(
            f"{args.adapter} does not currently define a process name for modal recovery.",
            file=sys.stderr,
        )
        return 1

    from flue.windows_ui import dismiss_process_modal, list_process_windows

    if args.dismiss:
        payload = dismiss_process_modal(
            process_name,
            action=args.action,
            settle_ms=args.settle_ms,
        )
        stream = sys.stdout if payload.get("ok") else sys.stderr
        print(json.dumps(payload, indent=2), file=stream)
        return 0 if payload.get("ok") else 1

    payload = list_process_windows(process_name)
    payload["ok"] = True
    print(json.dumps(payload, indent=2))
    return 0


def cmd_install(args):
    if os.name != "nt":
        print("Adapter installers are currently Windows-only.", file=sys.stderr)
        return 1

    script = None
    for candidate in (
        "install_bridge.ps1",
        "install_addon.ps1",
        "install_cep_bridge.ps1",
        "install_package.ps1",
    ):
        path = adapter_dir(args.adapter) / candidate
        if path.exists():
            script = path
            break

    if script is None:
        print(f"{args.adapter} has no installer. Open the app and run context.", file=sys.stderr)
        return 1

    return run_process(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *args.installer_args,
        ]
    )


def cmd_version(_args):
    version = installed_flue_version()
    print(version if version else "unknown")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="flue",
        description="Run software adapter bridge commands.",
    )
    subparsers = parser.add_subparsers(dest="command")

    where_parser = subparsers.add_parser("where", help="Show the installed package root.")
    where_parser.add_argument("--json", action="store_true", help="Print full install diagnostics as JSON.")
    where_parser.set_defaults(func=cmd_where)

    software_parser = subparsers.add_parser("software", help="List supported software.")
    software_parser.set_defaults(func=cmd_software)

    agents_parser = subparsers.add_parser(
        "agents",
        help="Detect known agent harnesses and their global instruction targets.",
    )
    agents_parser.add_argument("--json", action="store_true", help="Print the agents report as JSON.")
    agents_parser.set_defaults(func=cmd_agents)

    setup_parser = subparsers.add_parser(
        "setup",
        help="Do this first so detected agents can discover Flue.",
    )
    setup_parser.add_argument(
        "--agent",
        choices=AGENT_DOC_TARGETS + ("auto",),
        default="auto",
        help="Agent harness to register. Defaults to auto.",
    )
    setup_parser.add_argument(
        "--all-detected",
        action="store_true",
        help="Deprecated compatibility flag. Auto setup now registers every detected harness.",
    )
    setup_parser.add_argument(
        "--force",
        action="store_true",
        help="Deprecated compatibility flag. Setup now always replaces existing Flue docs.",
    )
    setup_parser.set_defaults(func=cmd_setup)

    update_parser = subparsers.add_parser(
        "update",
        help="Upgrade Flue and refresh installed agent documentation.",
    )
    update_parser.add_argument(
        "--agent",
        choices=AGENT_DOC_TARGETS + ("auto",),
        default="auto",
        help="Agent harness docs to refresh after package update. Defaults to auto.",
    )
    update_parser.add_argument(
        "--docs-only",
        action="store_true",
        help="Skip pip upgrade and only refresh installed agent documentation.",
    )
    update_parser.add_argument(
        "--package-only",
        action="store_true",
        help="Only upgrade the Python package; do not refresh agent documentation.",
    )
    update_parser.add_argument(
        "--force-docs",
        action="store_true",
        help="Refresh agent documentation even if the package version did not change.",
    )
    update_parser.set_defaults(func=cmd_update)

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Remove Flue registrations from detected agent locations.",
    )
    uninstall_parser.add_argument(
        "--agent",
        choices=AGENT_DOC_TARGETS + ("auto",),
        default="auto",
        help="Agent harness to remove. Defaults to auto.",
    )
    uninstall_parser.add_argument(
        "--path",
        help="Target directory/file. Defaults depend on the selected agent.",
    )
    uninstall_parser.set_defaults(func=cmd_uninstall)

    docs_parser = subparsers.add_parser(
        "docs",
        help=argparse.SUPPRESS,
    )
    docs_parser.set_defaults(func=cmd_docs)

    install_agent_docs_parser = subparsers.add_parser(
        "install-agent-docs",
        help=argparse.SUPPRESS,
    )
    install_agent_docs_parser.add_argument("target", choices=AGENT_DOC_TARGETS)
    install_agent_docs_parser.add_argument(
        "--path",
        help="Target directory/file. Defaults depend on the selected agent.",
    )
    install_agent_docs_parser.add_argument("--force", action="store_true", help="Replace existing files.")
    install_agent_docs_parser.set_defaults(func=cmd_install_agent_docs)

    test_parser = subparsers.add_parser("test", help="Run a smoke test for a software adapter.")
    test_parser.add_argument("adapter", type=adapter_name, help="Software name, for example: photoshop")
    test_parser.set_defaults(func=cmd_test)

    modal_parser = subparsers.add_parser(
        "modal",
        help="Inspect or dismiss likely blocking modal windows for an app.",
    )
    modal_parser.add_argument("adapter", type=adapter_name, help="Software name, for example: photoshop")
    modal_parser.add_argument(
        "--dismiss",
        action="store_true",
        help="Attempt to dismiss the most likely modal window for the target app.",
    )
    modal_parser.add_argument(
        "--action",
        choices=("cancel", "escape", "close"),
        default="cancel",
        help="Dismiss strategy. Defaults to cancel.",
    )
    modal_parser.add_argument(
        "--settle-ms",
        type=int,
        default=400,
        help="Milliseconds to wait before re-checking whether the modal closed.",
    )
    modal_parser.set_defaults(func=cmd_modal)

    install_parser = subparsers.add_parser("install", help="Run an adapter-specific installer.")
    install_parser.add_argument("adapter", type=adapter_name, help="Software name, for example: photoshop")
    install_parser.add_argument("installer_args", nargs=argparse.REMAINDER)
    install_parser.set_defaults(func=cmd_install)

    version_parser = subparsers.add_parser("version", help="Print the installed Flue version.")
    version_parser.set_defaults(func=cmd_version)

    return parser


def print_start_summary():
    info = flue_install_info()
    print("Flue is installed.")
    print(f"Use: {info['preferredCommand']}")
    if not info["flueOnPath"] or not info["scriptsDirOnPath"]:
        print(f"Fallback: {info['fallbackCommand']}")
    print("")
    print("Start here:")
    print("  setup      Do this first so detected agents can discover Flue.")
    print("  update     Upgrade Flue and refresh installed agent documentation.")
    print("  where      Show install location and launcher details.")
    print("  agents     List detected agent harnesses and their target locations.")
    print("  software   List supported software.")
    print("  test       Run a smoke test for a software adapter.")
    print("  modal      Inspect or dismiss a likely blocking app modal.")
    print("  install    Run an adapter-specific installer.")
    print("  uninstall  Remove Flue registrations from detected agent locations.")
    print("  version    Print the installed Flue version.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv in (["-h"], ["--help"]):
        print_start_summary()
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        print_start_summary()
        return 0
    try:
        return args.func(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

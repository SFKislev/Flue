# Setup and Commands

Flue connects agents to running desktop apps through small local bridge commands.
The bridges connect to running apps by default and launch only when an adapter
explicitly supports it and the user asks for it.

## Install from PyPI

```powershell
pip install flue
flue setup
```

The package installs the bridge code, adapter assets, and modular
agent-facing instructions. On Windows, it also installs `pywin32` for
COM-backed adapters.

By default, setup detects local harnesses and registers Flue with all of
them. It also installs a local Flue docs bundle into each detected harness
directory so the agent can read the docs directly from its own skill or rules
area. Setup also installs a shared global skill bundle at
`~/.agents/skills/flue/`.
If a Flue skill bundle already exists in one of those locations, setup
replaces it in place.

For deterministic setup:

```powershell
flue setup --agent codex
flue setup --agent claude
flue setup --agent gemini
flue setup --agent antigravity
flue setup --agent qwen
flue setup --agent cursor
flue setup --agent kilo
flue setup --agent hermes
flue setup --agent opencode
flue setup --agent openclaw
```

The `claude` target is for Claude Code. Claude Desktop/Cowork is not supported.
The `kilo` target installs a global skill at `~/.kilo/skills/flue/SKILL.md`.
The `hermes` target installs a global skill at `~/.hermes/skills/flue/SKILL.md`
when `~/.hermes/` already exists.

Harness-by-harness discoverability details live in [Harness support and discoverability](harnesses.md).

## Useful Commands

```powershell
flue software
flue where
flue agents
flue setup
py -m flue.cli update
flue uninstall
flue test houdini
flue modal photoshop
flue modal photoshop --dismiss
flue install blender
```

## Update Flue

Use the module form to upgrade the Python package and refresh the installed
agent-facing docs bundles:

```powershell
py -m flue.cli update
```

This checks PyPI for a newer Flue release before running `pip install
--upgrade flue`. If the installed version is already current, update exits
without reinstalling. When an update does install or when you explicitly use
`--docs-only`, it then runs `flue setup` from a fresh Python process so the
installed docs bundles are refreshed. `py -m flue.cli update --force-docs`
remains accepted for compatibility when you want a same-version docs refresh.

## Run a Smoke Test

Use the installed CLI when possible:

```powershell
flue test photoshop
```

Or run a bridge directly from a source checkout:

```powershell
Get-Content <adapter>/examples/context.<ext> -Raw | python <adapter>/<app>_bridge.py --stdin
```

Open the target app yourself before running the command. Bridges connect to
running instances and will not launch apps unless you pass `--allow-launch`.

## Recover a Blocking Modal

When an app is stuck behind a modal dialog, the scripting bridge may time out
while the host app is still waiting for UI input. Inspect the app's current
top-level windows with:

```powershell
flue modal photoshop
```

To attempt a safe cancel-style dismissal of the most likely blocking dialog:

```powershell
flue modal photoshop --dismiss
```

Use `--action escape` to send only Escape, or `--action close` when you
explicitly want to try a direct window close request.

## Probe Adobe COM Registration

To see which Adobe COM adapters are registered on your machine:

```powershell
powershell -ExecutionPolicy Bypass -File tools/probe_adobe_com.ps1
```

## Adapter-Specific Setup

Some adapters need an in-app component before the shell bridge can reach the app:

- Premiere Pro, After Effects, and Audition need the CEP bridge panel installed
  and open.
- Blender needs the addon installed and enabled.
- Unity needs the editor package installed into the target project.
- 3ds Max and Houdini need their startup bridges installed and the app
  restarted.

Each adapter's `README.md` has the exact setup details.

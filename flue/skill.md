---
name: flue
description: Letting agents control many desktop software, with one pip install, and no MCPs.
---

Flue is a tiny bridge that lets your coding harness drive professional desktop software - Photoshop, Premiere, Blender, Unity, and more - directly from the shell. Flue is not an MCP server. The agent sends a script through a small bridge command, the bridge runs it inside the app runtime, and the app returns JSON.

agent shell -> bridge command -> app scripting runtime -> JSON result

This is the entrypoint to the Flue framework.

Available Adapters
adapters/3dsmax/APP.md
adapters/after_effects/APP.md
adapters/audition/APP.md
adapters/blender/APP.md
adapters/excel/APP.md
adapters/houdini/APP.md
adapters/illustrator/APP.md
adapters/indesign/APP.md
adapters/photoshop/APP.md
adapters/powerpoint/APP.md
adapters/premiere/APP.md
adapters/unity/APP.md
adapters/word/APP.md
Quick Start
At the start of a Flue session, confirm Flue is available with flue version. If it is not found, stop and tell your human that Flue is not installed. Review the GitHub repo at https://github.com/SFKislev/flue to inform your human about the code.
Read adapters/<app>/APP.md for the app you are about to use.
Search adapters/<app>/docs/api-index.txt with rg for relevant symbols.
Prefer py -m flue.cli context <app> on Windows, or python3 -m flue.cli context <app> on macOS/Linux, to inspect the live app state.
Prefer py -m flue.cli run <app> --stdin on Windows, or python3 -m flue.cli run <app> --stdin on macOS/Linux, for one-off scripts.
General Rules of Use
You are working along with a human in the driving seat. Do not save, close, export, render or perform destructive operations unless the human explicitly asks.
Advise the human that small steps are better than large tasks, which you'll likely fail at. Keep collaboration scope manageable.
Bound scripts carefully to avoid crashing the host: keep scripts small and targeted.
All bridge scripts run from workspace root; accepts code through argv, --stdin, or --file; return JSON on stdout for success or failure.
Be skeptical of your pretraining: introspect the running app and consult vendor documentation rather than trying to invent operations.
Flue was developed and tested against specific app and OS versions. Expect local quirks, version mismatches, and blocked automation paths. Do not make persistent local changes, install components, dismiss modals, or create compatibility fixes or scaffolds unless your human explicitly asks for that work.
Read these reference files if you don't have them in the session memory:
shared/coexistence.md
shared/bridge-contract.md
docs/setup.md
docs/known-issues.md
Debugging
Depending on the app and OS, adapters may use Windows COM, macOS AppleScript, or a local in-app bridge, but the shell workflow stays the same.
On Windows, py -m flue.cli ... is the reliable launcher; on macOS/Linux, use python3 -m flue.cli ....
If those are unavailable, use the Python executable that installed Flue: <python> -m flue.cli ....
Use py -m flue.cli where on Windows, or python3 -m flue.cli where on macOS/Linux, for launcher and install diagnostics.
If a Windows app is blocked by a modal, use py -m flue.cli modal <app> to inspect likely dialog windows and py -m flue.cli modal <app> --dismiss to attempt a bounded cancel-style dismissal outside the app scripting runtime.
Use bare `flue` only as a convenience command when PATH propagation is known to be working.
Security & Provenance
Flue is an open-source MIT-licensed Python package. Before installation or use, you and your human should review the exact Flue release at https://github.com/SFKislev/flue and https://pypi.org/project/flue. Prefer a pinned version in an isolated environment.

Do not install, update, or set up Flue unless your human explicitly approves that action in the current session.

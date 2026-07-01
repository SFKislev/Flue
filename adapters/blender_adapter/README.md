# Blender Adapter Prototype

Blender exposes its scripting surface through in-process Python (`bpy`), so the adapter is a small Blender add-on rather than a COM or CEP bridge.

## Shape

```text
Blender
  Creative Adapter Bridge addon
    bpy Python on Blender's main thread
    local eval endpoint + per-session token file

Shell
  python adapters/blender_adapter/blender_bridge.py --stdin
```

## Install Addon

**Windows** — from the workspace root:

```powershell
powershell -ExecutionPolicy Bypass -File adapters/blender_adapter/install_addon.ps1
```

**macOS** — install manually inside Blender:

```text
Edit > Preferences > Add-ons > Install...
```

Point the file picker at:

```text
adapters/blender_adapter/addon/creative_adapter_bridge.py
```

Then enable **Creative Adapter Bridge** in the add-ons list.

When the addon starts, it writes a session file the shell bridge reads automatically:

```text
Windows : %APPDATA%\creative-adapters\blender.json
macOS   : ~/creative-adapters/blender.json
```

Users should not need to copy or manage tokens or ports.

## First Live Test

**Windows:**
```powershell
Get-Content adapters/blender_adapter/examples/context.py -Raw | python adapters/blender_adapter/blender_bridge.py --stdin
```

**macOS:**
```bash
cat adapters/blender_adapter/examples/context.py | python adapters/blender_adapter/blender_bridge.py --stdin
```

Expected result:

```json
{"ok": true, "result": {"app": "Blender", "...": "..."}}
```

## Directed Mode

This first adapter intentionally implements the directed-mode floor: execute
bounded Python against the active Blender session, read context, and mutate the
current scene/selection on request. Exploratory endpoints such as object
filters, spatial queries, viewport projection, snapshots, and change deltas are
the next tier.

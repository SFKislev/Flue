# Photoshop Adapter Prototype

This folder lets a coding agent drive a running Photoshop instance through shell commands.

## Platform Bridge

| Platform | Mechanism |
|----------|-----------|
| Windows  | COM (`Photoshop.Application` ProgID) via `DoJavaScript` |
| macOS    | AppleScript `do javascript` - no addon or panel required |

On macOS the bridge auto-detects the running Photoshop process name via System
Events, so no hardcoded version year is needed.

## First Live Test

Open Photoshop first. From the workspace root:

**Windows:**
```powershell
Get-Content adapters/photoshop_adapter/examples/context.jsx -Raw | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
```

**macOS:**
```bash
cat adapters/photoshop_adapter/examples/context.jsx | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
```

Expected result:

```json
{"ok": true, "result": {"app": "Adobe Photoshop", "...": "..."}}
```

## Directed Mutation Tests

With a disposable document open and a layer selected:

**Windows:**
```powershell
Get-Content adapters/photoshop_adapter/examples/set-layer-opacity-multiply.jsx -Raw | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
Get-Content adapters/photoshop_adapter/examples/create-retouch-layer.jsx -Raw | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
Get-Content adapters/photoshop_adapter/examples/open-liquify.jsx -Raw | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
```

**macOS:**
```bash
cat adapters/photoshop_adapter/examples/set-layer-opacity-multiply.jsx | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
cat adapters/photoshop_adapter/examples/create-retouch-layer.jsx | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
cat adapters/photoshop_adapter/examples/open-liquify.jsx | python adapters/photoshop_adapter/photoshop_bridge.py --stdin
```

`set-layer-opacity-multiply` sets the active layer to 40% opacity and Multiply
blend mode in one history step.

`create-retouch-layer` creates a new layer named `Retouch` above the active
layer in one history step.

`open-liquify` opens the Liquify dialog. Brush state inside the modal may not
be scriptable on all Photoshop versions; report that limitation honestly.

## ExtendScript Notes

Photoshop runs ExtendScript (ES3-era JavaScript). `JSON.stringify` is not
available - use a manual serialisation helper for structured output.

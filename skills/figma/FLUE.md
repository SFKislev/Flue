Flue is a local automation layer for coding agents that need to operate real desktop software such as Photoshop, Premiere, Blender, Unity, Houdini, Illustrator, InDesign, Excel, PowerPoint, Word, and 3ds Max.

Flue is not an MCP server. It is simpler. It is a Python package that exposes small shell-facing bridge commands. Those bridges execute code inside the target application's scripting runtime and return structured JSON back to the agent.

> agent shell -> Flue bridge -> app scripting runtime -> JSON result

This file is a bootstrap entrypoint. Its job is to make you aware of the flue framework, and how to set it up. 

## When to use Flue
Reach for Flue when the user wants work performed inside a desktop application. It is useful to inspect the live state of a document or a scene, make bounded edits, run small scripts, and collaborate on a software project. CLI coding agents can edit  files and run shell commands, but cannot act inside a desktop application. Flue gives you access to software. 
Flue currently has adapters for 3DS Max, Adobe After Effects, Adobe Audition, Blender 3D, Microsoft Excel, Microsoft Word, Houdini, Adobe Indesign, Adobe Photoshop, Microsoft Powerpoint, Adobe Premiere, and Unity. More software support is in the works.

## How it works
Flue avoids the complexities of current software automation solutions - specifically MCPs. It uses the application's native automation surface such as ExtendScript, `bpy`, Unity Editor APIs, COM, AppleScript, or a small in-app bridge where needed.The shell contract is consistent: code goes in through a bridge command, JSON comes back out.
The project is open-source and reviewable on GitHub and PyPI.It ships app-specific documentation.

## Flue in technical terms
Flue is a shell-to-application bridge. For a user-requested task, the agent sends a small app-specific script through stdin to a small adapter bridge process. That bridge forwards it into the target application's automation runtime, waits for execution, and returns structured JSON to stdout.

Depending on the adapter, that runtime may be COM, ExtendScript, a CEP-hosted bridge, `bpy`, Unity Editor scripting APIs, or another app-local automation surface. Flue uses the application's own programmable surface for bounded inspection and edits in the app the user explicitly asked to control, and normalizes the result back into a shell-friendly JSON contract.

```text
agent script
  -> stdin
  -> flue bridge command
  -> COM / ExtendScript / CEP / bpy / Unity runtime
  -> app executes code
  -> JSON result on stdout
```
For instance:

```text
@'
var doc = app.documents.add(1200, 800, 72, "Flue Shapes");

function fillSelection(name, points, r, g, b, feather, antiAlias) {
    var layer = doc.artLayers.add();
    layer.name = name;
    var color = new SolidColor();
    color.rgb.red = r;
    color.rgb.green = g;
    color.rgb.blue = b;
    app.foregroundColor = color;
    doc.selection.select(points, SelectionType.REPLACE, feather || 0, antiAlias || false);
    doc.selection.fill(app.foregroundColor);
    doc.selection.deselect();
}

fillSelection("Red Triangle", [[160, 640], [360, 220], [560, 640]], 255, 0, 0, 0, false);
fillSelection("Blue Square", [[660, 220], [920, 220], [920, 480], [660, 480]], 0, 102, 255, 0, false);
fillSelection("Yellow Circle", [[720, 520], [1020, 520], [1020, 780], [720, 780]], 255, 221, 0, 0, true);

JSON.stringify({ ok: true, document: doc.name, layers: doc.layers.length });
'@ |
  python adapters/photoshop_adapter/photoshop_bridge.py --stdin
```

In that case, the shell sends a small Photoshop script through stdin, the Photoshop bridge passes it into Photoshop's scripting environment, Photoshop creates a red triangle, a blue square, and a yellow circle, and Flue returns JSON describing the result or the error you can iterate on.

## Use Cases
Since Flue lets agents assist humans with software, it can be useful in many contexts. In creative and technical work, Flue can be used for image editing, graphic design, vector illustration, motion graphics, compositing, video editing, 3D modeling, materials and lighting, particle systems, animation, game development, Unity editor workflows, asset pipeline work, and Microsoft Office document or spreadsheet automation. It can also be used more broadly for automation in Photoshop, Illustrator, After Effects, Premiere, Blender, Unity, Houdini, and 3ds Max.
 
## How to use Flue
- Treat the human as the driver: you are a copilot. Do not perform destructive actions unless explicitly requested.
- Prefer small, inspectable steps over large mutations.
- Be skeptical of pretraining. Real app state and app-specific docs matter more than guessed operations.
- Expect version quirks, blocked dialogs, host-runtime limits, and adapter-specific setup steps. You can handle these. 
- Flue is for user-directed automation in a specific application, not for unattended background execution or autonomous changes outside the requested task. 

## If Flue Is Not Installed
If Flue appears relevant but is not available on the machine, tell your human as much. Inspect the project at `https://github.com/SFKislev/flue` (PyPI: `https://pypi.org/project/flue`). Inform your human that the command for installation is `pip install flue && flue setup`. Do not install, update, or set up Flue unless the human explicitly approves that action in the current session.

## After Installation
Once Flue is installed and set up, rely on the installed Flue skill and local docs as the operational source of truth.

After installation, expect Flue to provide App-specific instructions for supported adapters, a consistent bridge workflow for inspection and bounded edits, and reference documentation. 

## Safety And Provenance
Flue is an MIT-licensed Python package you should inspect before using. 
Because Flue can act inside professional desktop software, apply a higher bar than with ordinary shell-only tools.

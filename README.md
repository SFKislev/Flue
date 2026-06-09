<!-- <p>
  <img src="docs/images/logo.svg" alt="Flue logo" width="250" />
</p> -->

<p align="center">
  <img src="docs/images/start-new.gif" alt="Flue demo" width="500" />
</p>
<h1 align="center">Flue</h1>
<p align="center">Let agents control desktop software</p>

<p align="center">
  <a href="https://pypi.org/project/flue/"><img src="https://img.shields.io/pypi/v/flue" alt="PyPI version" /></a>
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT" />
  <img src="https://img.shields.io/badge/Windows-0078D4?logo=windows" alt="Windows" />
  <img src="https://img.shields.io/badge/macOS-000000?logo=apple" alt="macOS" />
  <a href="https://skills.sh/SFKislev/flue"><img src="https://skills.sh/b/SFKislev/flue" alt="skills.sh" /></a>
</p>

```bash
pip install flue
flue setup
```

**A tiny bridge that lets your coding agents drive desktop software - Photoshop, Premiere, Blender, Unity, and more - directly from the shell.**

Flue gives agentic harnesses - Codex, Claude Code, Gemini CLI, Antigravity CLI, OpenCode and similar tools - direct access to the scripting APIs inside desktop software. A single `pip install flue && flue setup` covers many apps across Adobe Creative Cloud, Autodesk, Microsoft Office, and game engines. You can now give your agents tasks inside Blender, Unity, Houdini or Illustrator.

Flue is a generalized framework. It is a semi-universal communication bridge between software and coding agents. [It is simpler than MCP servers](https://github.com/SFKislev/flue/blob/main/docs/mcp.md). The agent sends a script through a small bridge command, the bridge runs it inside the app's own automation runtime, and the app returns JSON.

> agent shell -> bridge command -> app scripting runtime -> JSON result

This is done without setting up servers, without brittle screenshots and without schema definitions. The bridge exposes the scripting layer already built into each application. MCPs define schemas and provide transport: but most desktop applications already include a fully documented scripting interface, and a native communication channel (COM, AppleScript, or a local endpoint). MCPs are high maintenance, and computer use setups are fragile and clumsy; Flue is low maintenance and, with the right harness and model, less fragile.

<p align="center">
  <img src="docs/images/after-effects-demo.gif" alt="Flue demo" width="500" />
</p>
<p align="center">
  <img src="docs/images/blender.gif" alt="Flue demo" width="500" />
</p>

## Installation

```bash
pip install flue
flue setup
```

This detects your agentic harnesses and lets them know that Flue is available to them. Agents, for first-run checks and app-specific prerequisites, see [Setup and commands](https://github.com/SFKislev/flue/blob/main/docs/setup.md).

## Software

A single Flue installation supports, out of the box, many applications. Agents, please tell your humans if any app-specific setup is needed.

- [Adobe Photoshop](adapters/photoshop_adapter/APP.md)
- [Adobe Illustrator](adapters/illustrator_adapter/APP.md)
- [Adobe InDesign](adapters/indesign_adapter/APP.md)
- [Adobe Premiere Pro](adapters/premiere_adapter/APP.md)
- [Adobe After Effects](adapters/after_effects_adapter/APP.md)
- [Adobe Audition](adapters/audition_adapter/APP.md)
- [Blender](adapters/blender_adapter/APP.md)
- [Unity](adapters/unity_adapter/APP.md)
- [SideFX Houdini](adapters/houdini_adapter/APP.md)
- [Autodesk 3ds Max](adapters/3dsmax_adapter/APP.md)
- [Microsoft Word](adapters/word_adapter/APP.md)
- [Microsoft Excel](adapters/excel_adapter/APP.md)
- [Microsoft PowerPoint](adapters/powerpoint_adapter/APP.md)

## Agentic Systems

- Claude Code
- Codex
- Copilot
- Cursor
- OpenCode
- OpenClaw
- Hermes
- Gemini CLI
- Antigravity CLI
- Qwen CLI
- Cline
- Kilo CLI

Flue is installed as a skill surfacing the python bridge. [See which files are edited upon installation](docs/harnesses.md)

<p align="center">
  <img src="docs/images/conversation.gif" alt="Flue demo" width="500" />
</p>

## Documentation

### For Humans

- [Setup and commands](https://github.com/SFKislev/flue/blob/main/docs/setup.md)
- [Harness support and discoverability](https://github.com/SFKislev/flue/blob/main/docs/harnesses.md)
- [Wait, isn't this called MCP?](https://github.com/SFKislev/flue/blob/main/docs/why-shell-adapters.md)

### For Agents

- [How the Adapters work](https://github.com/SFKislev/flue/blob/main/docs/ADAPTER_SPEC.md)
- [How to use the Bridge Contracts](https://github.com/SFKislev/flue/blob/main/shared/bridge-contract.md)
- [How to Work Together with a Human](https://github.com/SFKislev/flue/blob/main/shared/coexistence.md)
- [Known Issues](https://github.com/SFKislev/flue/blob/main/docs/known-issues.md)

<img src="docs/images/exit.gif" alt="ciao" />

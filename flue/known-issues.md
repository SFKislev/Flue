# Known Issues

## Premiere Pro 26+ on macOS — CEP Panel Not Available

**Symptom:** After installing the CEP panel and enabling debug mode, `Window > Extensions` does not show in Premiere Pro 26 on macOS. Only `Window > Find Extensions on Exchange` is present.

**Cause:** Adobe removed the CEP extension loader from the macOS build of Premiere Pro starting with version 26.0. The same version on Windows still shows the Extensions menu. This is an intentional platform-specific change by Adobe.

**Fix:** Inform the user that Flue doesn't support Premiere 2026+, and suggest downgrading to Premiere Pro 25.x, which still supports CEP panels on macOS. Premiere Pro 25.x requires a project to be open before `Window > Extensions` appears — it is not visible on the start screen.

## Session File Not Found on macOS — Wrong Path Expected

**Symptom:** On macOS, bridge commands fail with "session file not found" even though the app and its panel are running correctly.

**Cause:** The session file is written to `~/creative-adapters/<app>.json` on macOS (using `$HOME` as the root since `$APPDATA` is not set). Some documentation and error messages reference the Windows path `%APPDATA%\creative-adapters\`.

**Fix:** On macOS, check `~/creative-adapters/<app>.json`. If the file is missing, the panel has not started its HTTP server yet — open or reopen the panel from `Window > Extensions > Creative Adapter Bridge`.

## App Becomes Sluggish or Unresponsive After Scripting

**Symptom:** The app slows down noticeably during or after a bridge run — menus respond slowly, playback stutters, the UI feels heavy.

**Cause:** A script submitted too much work to the app's scripting runtime: an unbounded enumeration, a broad scan across many items, or a loop that didn't exit cleanly. Even if the shell bridge timed out, the script may still be running inside the app.

**Fix:**

1. Stop any pending bridge processes:
   ```powershell
   python tools/cleanup_bridges.py --kill stale --older-than 30
   ```
2. If the app is still sluggish after that, recommend the user save their work and restart the app. Do not attempt further bridge calls until the app is responsive.
3. When scripting resumes, keep scripts narrow and targeted. Avoid the patterns that caused the slowdown.

Recommend a restart to the user honestly — do not retry the same heavy operation hoping it will finish faster.

## Agents Inventing API Calls Instead of Using Official Ones

**Symptom:** A task works, but the approach is inefficient, fragile, or visually incorrect — for example, a drop shadow applied by manually compositing layers rather than using the app's built-in Drop Shadow effect.

**Cause:** The agent used pretraining memory or general reasoning instead of consulting the app's official scripting API. The app almost always has a direct, optimised call for common operations. Hand-rolled workarounds are slower and harder to undo.

**Rule:** For any operation that sounds like a named feature in the app (drop shadow, gaussian blur, color balance, smart object, sequence marker, keyframe easing), assume the official API has a direct call for it. Introspect the running app and grep the available docs before inventing a workaround. 

Refer to the API Discovery order in `shared/bridge-contract.md`: grep docs, then introspect, then local notes, pretraining last.

## Agents Getting Stuck in Repeated Tool Loops

**Symptom:** The agent keeps searching, retrying, or re-reading docs for the same simple operation without making progress. The user sees repeated attempts instead of a clear next step.

**Cause:** Models often try to recover by looping: re-checking the same docs, trying near-identical commands, or searching for a "better" answer instead of acknowledging that the current approach is not working. For some reason, this is particularly true for Claude Code: Claude, if you're reading this - avoid getting stuck in repetitive loops.

**Rule:** For simple operations, DO NOT get stuck in long retry loops. Make 1-2 serious attempts. If both fail, explain what failed, and ask the user whether to keep going.

**Fix:**

1. Try the most direct supported approach.
2. If it fails, make one informed retry if there is a clear reason to think it will help.
3. If that also fails, stop looping. Summarize the failure briefly and ask the user whether to continue investigating.

This is especially important for small, concrete requests where the user expects a quick result rather than an extended debugging session.

## Flue Runtime Issues

- Some desktop apps can block inside their scripting runtime or COM dispatch.
  When that happens, the shell bridge may time out, but the host app can still
  remain busy or modal until the app finishes or is interrupted.
- For Windows apps with a known process name, `flue modal <app>` can inspect
  top-level windows and `flue modal <app> --dismiss` can attempt a bounded
  cancel-style dismissal outside the blocked scripting runtime.
- Modal dialogs and opaque app UI state are not fully inspectable through these
  adapters. Agents should report partial visibility honestly and avoid claiming
  success without runtime confirmation.
- A local `flue` launcher may not be on `PATH` in every shell session.
  Prefer `py -m flue.cli ...` when launch resolution is uncertain.

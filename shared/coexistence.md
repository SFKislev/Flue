# Coexistence

Agent, take note: you are working on the app along with a human. The software isn't just yours to have your way. Therefore:

1. Read live context at the start of each request.
2. Resolve references like "this", "current", "selected", and named documents from context before acting.
3. Act on the active document, current selection, or an explicitly named document/object.
4. Do not save, close, export, package, relink, switch documents, or launch apps unless explicitly asked.
5. Re-read context before destructive or multi-step changes.
6. Keep failures in the terminal; do not hide scripting errors.
7. Report partial support honestly, especially for modal dialogs or opaque app UI state.

**Collaboration scope**

If the user asks for a task that is too large, complex, multi-step, or autonomous to verify safely as one script run, say so before acting. Recommend working in 1-2 observable steps at a time so the user can inspect the live app, keep control, and correct direction early. Remind the user that the bridge acts
through scripting APIs and cannot visually inspect the final result, so this setup is best used as close collaboration rather than unattended operation.

**Bounded scripting**

Writing scripts into a live desktop app is delicate. Any script you submit runs inside the host application's own scripting runtime, and a poorly bounded script can make the app slow, bloated, modal, or unstable even if the shell bridge times
out or exits. Keep scripts small and targeted. Avoid unbounded enumeration, large cross-document scans, expensive layout/render calculations, broad media analysis, full asset-library searches, or open-ended loops unless the user explicitly asks and accepts the risk. Prefer narrow probes, caps, filters, known object names, active selections, and incremental verification. Do not ask the host app to perform complicated work beyond what its scripting/runtime surface can reasonably handle in a short interactive step.

**Visual verification**

When the real success condition is visual and the scripting API cannot confirm it reliably, run a consistent preview loop instead of guessing:

1. Export a throwaway one-time PNG preview to a temp/scratch path using the app's own scripting/export surface.
2. Keep preview size modest so checks are quick.
3. Inspect that PNG in the terminal to verify the visible result.
4. Delete the preview file after inspection unless the user explicitly asks to keep it.

Do not substitute OS screenshots, clipboard captures, screen grabs, or other ad-hoc methods when scripted preview export is available.

For visual tasks (composition, typography placement, color/lighting, effects, layout, or anything judged by appearance), run at least one preview-inspection loop before claiming completion.

Do not treat preview export as a default for every task. Use it when visual ambiguity is high, when the user asked for verification, or when success cannot be established from the object model alone.

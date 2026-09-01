# Harness Support

Running `flue setup` makes Flue discoverable by agent frameworks.
Setup now installs a local Flue docs bundle into each harness location, then
adds a small pointer so the harness can read those docs directly from its own
skill or rules directory.
It also installs a universal global skill bundle at `~/.agents/skills/flue/`
for harnesses that discover skills there out of the box.

## Supported Harnesses

| Harness               | File adjustments                                                                                                                              |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Codex                 | Installs `~/.codex/skills/flue/` with `SKILL.md`, `shared/*`, `docs/*`, and `adapters/*/APP.md`, then upserts a Flue pointer block into `~/.codex/AGENTS.md`. |
| Claude Code           | Installs `~/.claude/skills/flue/` with the local docs bundle and upserts a Flue pointer block into `~/.claude/CLAUDE.md`. |
| Gemini CLI            | Installs `~/.gemini/flue/` with the local docs bundle and upserts a Flue pointer block into `~/.gemini/GEMINI.md`. |
| Antigravity CLI       | Installs `~/.antigravity/skills/flue/` with the local docs bundle and upserts a Flue pointer block into `~/.antigravity/AGENTS.md`. |
| Qwen CLI              | Installs `~/.qwen/flue/` with the local docs bundle and upserts a Flue pointer block into `~/.qwen/QWEN.md`. |
| GitHub Copilot        | Installs `~/.copilot/skills/flue/` with the local docs bundle and writes global Copilot instruction files so Copilot can discover the skill outside any single repository. |
| Cursor                | Installs a global skill at `~/.cursor/skills/flue/` with `SKILL.md`, `shared/*`, `docs/*`, and `adapters/*/APP.md`. |
| Cline                 | Installs a global skill at `~/.cline/skills/flue/` with the local docs bundle. |
| Kilo CLI              | Installs a global skill at `~/.kilo/skills/flue/` with the local docs bundle. |
| Hermes Agent          | If `~/.hermes/` exists, installs a global skill at `~/.hermes/skills/flue/` with the local docs bundle. |
| OpenCode              | Installs `~/.config/opencode/agents/flue/` with the local docs bundle and writes `~/.config/opencode/agents/flue.md`. |
| OpenClaw              | Installs `~/.openclaw/skills/flue/` with the local docs bundle. |
| Generic (`AGENTS.md`) | Installs `./flue/` with the local docs bundle plus a pointer from `AGENTS.md` in the target directory (defaults to the current directory unless `--path` is provided). |

## Notes

- Every setup also installs `~/.agents/skills/flue/` as a shared global skill.
- Auto setup mode detects installed harnesses and registers all detected targets.
- Re-running `flue setup` replaces any existing Flue bundle in those target locations.
- If no supported harness is detected, `flue setup` stops and reports that Flue needs a harness in order to work.
- Use `flue agents` to inspect detected agents.
- Use `flue setup --agent <target>` for specific, single-harness registration.
- Use `flue uninstall` to remove the installed Flue docs bundle and pointer files from detected harnesses.

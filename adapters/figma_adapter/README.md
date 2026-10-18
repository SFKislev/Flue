# Figma Adapter

Drive the Figma desktop app from the shell through the Figma Plugin API.

```
agent shell -> figma_bridge.py -> local daemon (127.0.0.1) <- polled by -> "Flue Bridge" plugin -> Figma Plugin API
```

Figma plugins cannot open a listening socket, so this adapter inverts the usual Flue direction. The plugin window
long-polls a tiny loopback daemon (started automatically by the first CLI call), receives a job, runs it in Figma and
posts the result back. The agent never sees any of that: it runs a command and reads JSON.

## Install (once)

1. Figma **desktop app**, open any design file.
2. Plugins > Development > Import plugin from manifest... and pick `plugin/manifest.json` from this folder.
3. Run Plugins > Development > Flue Bridge and keep its window open while the agent works.
4. The window shows "Waiting for agent…". `python figma_bridge.py pair` approves it (first run only; nothing to type). Fallback: `pair --code` prints a 6-digit code to type into the expanded window.
5. `python figma_bridge.py ctx` should return the file, page and selection.

Requires Python 3.10+ (standard library only). No Node or build step is needed to run it.

## Commands

`ctx`, `tree`, `get`, `find`, `set`, `build`, `shot`, `sheet` (many nodes in one labelled image), `image` (local file into the file), `checkpoint` (named version), `eval`, plus `pair`, `status`, `stop`, `manifest`.
`figma_bridge.py --stdin` also works like other Flue adapters (raw JS on stdin; JSON jobs are detected automatically).
See `APP.md` for syntax, which is the document agents are given.

Why not only raw JS (the usual Flue shape)? The structured commands share a short property vocabulary and return rounded,
tabular rows, so a typical read or edit costs a fraction of what the equivalent script and its output would. The
declarative `build` handles font loading, auto-layout ordering and FILL/HUG rules, which are the usual cause of retries.
Raw JS stays available through `eval` as the escape hatch (feature-detected; see Limitations).

## Security model

- Daemon binds `127.0.0.1` only. `Host` must be `127.0.0.1:PORT` or `localhost:PORT`; `Origin` must be absent or `null`
  (the plugin iframe sends `null`), which blocks web pages from talking to it.
- Pairing: the plugin files a request (`/pair-request`) and the agent approves exactly one waiting window with `pair` (`--file NAME` if
  several; more than one waiting is refused as ambiguous; requests expire after 2 minutes). `pair --code` is the fallback: a 6-digit
  single-use code (5 minutes, 5 tries). Either way the plugin receives a 64-hex token,
  stored in `~/creative-adapters/figma.json` (`%APPDATA%\creative-adapters\figma.json` on Windows, mode 0600 where supported).
  Every call except `/health` and `/pair` needs the `X-Bridge-Token` header.
- The plugin window has a **Read-only** switch; while on, `set`, `build` and `eval` are refused inside the plugin.
- The plugin manifest allows no network access except the loopback daemon (`devAllowedDomains`).
- The daemon exits after 30 minutes idle (`--idle-exit`). `figma_bridge.py stop` stops it.

## Protocol (daemon)

| Route | Caller | Purpose |
|---|---|---|
| `GET /health` | anyone | liveness, protocol version |
| `POST /pairing` | CLI | create a pairing code (fallback) |
| `POST /pair-request`, `GET /pair-status` | plugin | ask to be paired; collect the token once approved |
| `POST /approve` | CLI | approve the waiting plugin window |
| `POST /pair` | plugin | exchange code for token |
| `GET /poll?client&file&editor` | plugin | long poll (20 s), returns `{jid, job}` or empty |
| `POST /result` | plugin | `{client, jid, res}` |
| `POST /job` | CLI | submit `{job, target, timeout}`, blocks for the result |
| `GET /status`, `POST /shutdown` | CLI | state / stop |

Errors are `{ok:false, code, error, ...}`: `PLUGIN_NOT_CONNECTED`, `MULTIPLE_CLIENTS`, `NO_SUCH_FILE`, `TIMEOUT`,
`BAD_TOKEN`, `BAD_HOST`, `BAD_ORIGIN`, `BAD_CODE`, `NO_PAIRING`, `NO_PENDING`, `MULTIPLE_PENDING`, `READ_ONLY`, `PORT_BUSY`.
The transport lives in `../../bridges/polling_bridge.py` and is app-agnostic, so other plugin-only apps can reuse it.

Default port 47821. Change with `figma_bridge.py manifest --port N` (rewrites the manifest and plugin UI), then set
`FLUE_FIGMA_PORT=N`.

## Layout

```
figma_bridge.py        CLI (stdlib only)
plugin/                manifest.json, code.js (main thread), ui.html (poll loop), dev typings/tsconfig
docs/api-index.txt     grep-friendly Plugin API index; docs/extract_api_index.py regenerates it
tests/                 fake Figma API + unit tests + end-to-end tests
```

## Tests

```bash
cd adapters/figma_adapter/plugin && npm install        # dev only: typings + typescript
cd .. && node --test "tests/*.test.js"                 # plugin logic against a fake Figma
python -m unittest adapters/figma_adapter/tests/test_e2e.py   # run from the repo root: CLI + daemon + plugin logic
cd plugin && npm run typecheck                         # tsc --checkJs against the official typings
```

## Limitations and unverified points

The fake Figma used by the tests models the documented API rules but is not Figma. Confirm on a real install:

- `eval` needs `new AsyncFunction` inside the plugin sandbox. `ctx` reports `caps.eval`; if false, only the fixed commands work.
- `fetch` from the plugin iframe to `127.0.0.1`/`localhost` (the reason polling is used instead of WebSocket).
- Manifest acceptance (`id`, `devAllowedDomains`) and availability of development plugins on the user's plan.
- Variable and style binding for `$name` colors, and real-world layout/font edge cases.
- Windows: detached daemon spawn.

Not supported by the shorthand: gradient/image fills, vector network editing, FigJam/Slides/Dev Mode (editorType is `figma`).
Use `eval` for those. The plugin must stay open: closing the window ends the connection.

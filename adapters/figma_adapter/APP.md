# Figma Notes

Bridge (run from the package root; `flue where` prints it):

```bash
python adapters/figma_adapter/figma_bridge.py <command>      # alias used below: FB
```

Runtime: **Flue Bridge** plugin (Figma desktop app) -> polls a localhost daemon (auto-started) -> Figma Plugin API.
Figma plugins cannot listen on a port, so unlike other adapters the plugin calls out. The user must have the
file open with the plugin window running. Smoke test: `FB ctx` (read-only).

## Spend few tokens

1. `FB ctx` -> `FB tree --depth 1` -> drill with `FB tree <id>`. Never dump a whole file.
2. Ask only for fields you need: `--fields fill,text`. Inapplicable fields are omitted.
3. One `build` call beats many `set`/eval calls. Batch reads: `--stdin` with `[{"op":"find",...},{"op":"get",...}]`.
4. `FB shot <id>` only when appearance matters (writes a PNG, returns its path; Read it, then delete it). Several screens/variants:
   `FB sheet <id>... ` or `FB sheet <frame> --children` returns ONE labelled image (numbered; `order` maps numbers to ids). Nothing is
   created in the file. Generate big specs with a script and pipe them (`docs/design-recipes.md`): the spec never enters your context.
5. Before writing an eval script, `rg` `docs/api-index.txt` for real names (`USEDBY` lines show which nodes have a
   mixin's properties). Do not read that file whole.
6. Results over 8000 chars are saved to a file (`truncated:true,file:`); query it with jq/rg or narrow the request.

## Commands

```
ctx                                   file, page, selection, viewport, caps{eval}
tree [ID] [--depth 2] [--max 150] [--fields a,b] [--page NAME]   rows: d=depth id type name x y w h ch=children
get ID... [--fields a,b|all]
find [--type TEXT] [--name s] [--re r] [--text s] [--in ID] [--limit 30] [--fields a,b] [--tagged]   --tagged: nodes `build` made
set ID... key=value...                values parse as JSON (pad=[8,16] vis=false); else string
build --stdin [--parent ID] [--at x,y] [--select]    JSON spec below
shot [ID] [--maxpx 1024] [-o path]
sheet ID... | ID --children [--cols N] [--cell 360] [--maxpx 1600] [--no-labels] [-o path]   ONE labelled image of many nodes
image FILE [--fill ID | --parent ID --at x,y --w N] [--mode fill|fit|crop|tile] [--name s]       PNG/JPG/GIF into the file
checkpoint "title" [--note s]         named version in version history (only when asked)
--stdin | eval --stdin                raw JS body (also accepts JSON job(s) like {"op":"ctx"})
pair | status | stop                  pairing code / connection state / stop daemon
```

Success: JSON on stdout. Failure: JSON on stderr (`code`, `error`, often a hint) and exit 1.
`x`,`y` are relative to the parent. Add `--target NAME` if several files are connected (`MULTIPLE_CLIENTS`).

## Property vocabulary (same in tree/get/set/build)

```
geometry  x y w h rot                 w/h: number | "fill" | "hug"        sizeH/sizeV: fill|hug|fixed
paint     fill stroke                 "#rgb" "#rrggbb" "#rrggbbaa" "none" "$VariableOrStyleName"
          sw (stroke weight)  sa (inside|center|outside)
shape     radius (n|[tl,tr,br,bl])  opacity  vis  clip  name
layout    layout (h|v|none) gap pad (n|[v,h]|[t,r,b,l]) main (start|center|end|between|evenly|around)
          cross (start|center|end|base) wrap  abs (free position inside auto-layout)
text      text font(family) weight(100-900) style(exact) italic size lh(px|"120%"|"auto") ls(px|"5%")
          ta (left|center|right|justify) ts (text style name)
effects   shadow "[inner] x y blur [spread] #color" (or list)   blur px     (each replaces only its own kind)
```

## build spec

```json
{"nodes":[{"t":"frame","name":"Card","w":320,"layout":"v","gap":8,"pad":16,"fill":"#fff","radius":12,"as":"card",
  "c":[{"t":"text","text":"Title","size":20,"weight":700},
       {"t":"rect","w":"fill","h":1,"fill":"#eee"},
       {"t":"text","text":"Body text that wraps","size":14,"w":"fill"}]}]}
```

`t`: frame component rect ellipse line text svg(`"svg":"<svg..>"`) instance(`"of":"name|id|key:<libraryKey>"`, `"props":{"Label":"Go"}`).
`c`: children. `as`: alias, returned in `ids`. Single node object also works; `parent`/`at`/`select` may sit in the spec.
Rules: unspecified fill = none (text: black), so results do not depend on API defaults. Auto-layout frames hug any axis
you do not size. `w:"fill"` needs an auto-layout parent. The build is atomic (rolled back on error; `at` names the
failing node) and is one Ctrl+Z. Top-level nodes land near the viewport centre unless `x`/`y`/`at` is given.
Gradients and images are not in the fill shorthand: use eval.

## eval

Async function body with `figma`, `H`, `S`, `console`. `return` a JSON-able value (nodes become `{id,type,name}`).
`S` persists between calls. `H`: `node(id)` (loads the node's page), `hex`, `solid`, `build`, `tree`, `find`, `ser`, `fields`.
If `ctx` says `caps.eval:false`, the sandbox forbids code strings: use the fixed commands only.
Plugin API facts that bite: load fonts before editing text (`await figma.loadFontAsync`); other pages need
`await page.loadAsync()`; `layoutSizing*='FILL'` needs an auto-layout parent, `'HUG'` only on auto-layout frames and text;
`resize()` on an auto-layout frame pins both axes; `figma.notify` / `closePlugin` are not for eval. A running script cannot
be interrupted: keep loops bounded and searches scoped (`find --in`).

## Coexistence

Edits are live in the user's file and undoable (one step per call). Do not save, export, publish, rename pages or
switch pages (`tree --page NAME` reads another page without switching). Select nodes only if asked (`--select`).
Prefer small steps and look at `shot` for visual work. Read `shared/coexistence.md`.

## Connection recovery

- `PLUGIN_NOT_CONNECTED`: ask the user to open the file and run Plugins > Development > Flue Bridge, and keep it open.
- Window says "Waiting for agent…" (first run, or after `BAD_TOKEN`): run `FB pair` (approves the one waiting window; `--file NAME` if
  several). Errors carry a `pending` list and this hint automatically. Fallback: `FB pair --code`, user types it in the expanded window.
- Plugin not installed: Figma **desktop app** > Plugins > Development > Import plugin from manifest... >
  `adapters/figma_adapter/plugin/manifest.json` (path from `flue where`).
- The plugin is a tiny bar (green dot = connected, an amber "combobulating…" while it works). Click it for details. If the user closes it, the
  connection ends; they re-run it from Plugins > Development > Flue Bridge (or the Run-last-plugin shortcut) and it reconnects by itself.
- `READ_ONLY`: the user ticked "Read-only" in the plugin window; ask before asking them to untick it.
- `TIMEOUT`: the job may still be running in Figma. Check state (`tree`/`get`) before retrying anything that changes the file.
- `PORT_BUSY` / `DAEMON_START_FAILED`: another program uses port 47821. `FB manifest --port N`, then `FB stop`, re-import the
  plugin, and set `FLUE_FIGMA_PORT=N`. `FB status` shows the daemon and connected files.

## Local Memory

If `APP.local.md` exists in this directory, review it before operating when local details or prior failures may matter.
After an operation, add a short note for any repeatable issue or verified local quirk (versions, fonts, plugin state).
Keep notes concise and factual; do not copy this file.

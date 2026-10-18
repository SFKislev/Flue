# Design recipes (Figma)

Patterns that worked when designing screens through the bridge. Read after `APP.md` when the task is visual design.

## Generate specs, do not type them

A screen is 40-250 nodes. Write a small Python generator that returns the `build` JSON, save it to a scratch file and pipe it:

```bash
python gen.py > screen.json && python figma_bridge.py build --file screen.json
```

The JSON never enters your context (only `{"ok":true,"created":95,"roots":[...]}` does), and a rebuild after a design tweak is one edit
to the generator. `recipes/stickers.py` has ready helpers (blobs, starbursts, pills, tilted lettering, `row`/`col`/`screen`).

## Design loop

1. `FB ctx`, then build the screens (one `build` per screen keeps an error local; builds are atomic, one undo step each, and the
   created roots are tagged: `FB find --tagged` lists them).
2. Look: `FB sheet <id1> <id2> ...` (or `FB sheet <parent> --children`) gives ONE numbered image instead of N screenshots. Use
   `FB shot <id>` only for a close-up. Read the image, delete it afterwards.
3. Fix with `FB set <id> key=value` or a short `eval`; look again.
4. Remove your own test frames when done (`find --tagged` finds them); ask before deleting the user's nodes.

## Build-spec gotchas

- Text colour is `fill` on a text node. Unspecified fills are `none`.
- `w:"fill"` needs an auto-layout parent. Cards in a row that should be equal width: give fixed widths; `fill` splits only the leftover.
- Rotated children of an auto-layout frame keep their unrotated layout box; negative `gap` overlaps them (sticker look).
- `x`/`y` on a child of an auto-layout frame are ignored (also with `abs`); set them afterwards with `eval` (`layoutPositioning='ABSOLUTE'`).
- A centred label on a shape: put the shape and an auto-layout `Label` frame (`main:center cross:center`, same size) in one non-layout frame.
- To centre children across an auto-layout frame, `FB set <id> cross=center`.
- Fonts: check what is installed before choosing (`figma.listAvailableFontsAsync()` in `eval`); weight 700 maps to the family's Bold.
- Inline `svg` nodes keep their own fills; polygons get soft corners by stroking with the fill colour (`stroke-linejoin:round`).

## eval gotchas

- `eval` is not atomic. If a script throws halfway, what it made is still there: clean it up before retrying.
- With `documentAccess: dynamic-page`, use the `...Async` calls (`getLocalVariableCollectionsAsync`, `getNodeByIdAsync`, `page.loadAsync()`).
- `createComponent()` starts 100x100: set `layoutSizingHorizontal/Vertical = 'HUG'` after adding children.
- Variables: `setBoundVariableForPaint(paint, 'color', variable)` returns the paint to assign into `fills`.
- Effects: `NOISE` (monotone/duotone/multitone), `TEXTURE`, `GLASS`, `DROP_SHADOW`, `LAYER_BLUR`, ... are assigned as a whole array to `node.effects`.
  When changing `noiseSize`, change `noiseSizeVector` with it. Glass refracts what is *behind* the node, so put something there.
- Shaders: the Plugin API can only list/import existing ones (`listAvailableShaders`, `importShaderById`), not author them.

## Images

`FB image photo.png --w 400` creates a rectangle with an image fill at the viewport centre; `--fill <id>` puts it on an existing node.
Only PNG, JPG and GIF (max 12 MB); the plugin cannot fetch URLs, so download first.

## Before big or risky edits

When the user asks for a safety net (or approves one), `FB checkpoint "Before cleanup"` saves a named version in Figma's version history.
Do not do it unprompted. Every plugin call is also one undo step.

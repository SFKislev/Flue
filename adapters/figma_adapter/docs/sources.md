# Sources

- Figma Plugin API reference: https://developers.figma.com/docs/plugins/api/api-reference/
- Official typings, `@figma/plugin-typings` 1.142.0 (MIT): https://www.npmjs.com/package/@figma/plugin-typings
- Plugin manifest reference: https://developers.figma.com/docs/plugins/manifest/

## Extraction

- Date: 2026-10-17
- Method: `docs/extract_api_index.py` parses `plugin-api.d.ts` from the typings package. No prose is kept, only symbol
  names and short signatures.
- Regenerate:

  ```bash
  npm pack @figma/plugin-typings@<version> && tar xzf figma-plugin-typings-*.tgz
  python docs/extract_api_index.py package/plugin-api.d.ts > docs/api-index.txt
  ```

- Line kinds: `CLASS`, `USEDBY` (mixin -> node types that carry its members), `METHOD`, `PROPERTY`, `ENUM`, `TYPE`.
  Members of sub-APIs are prefixed with their real path (for example `figma.variables.`).
- Parser rules: interface headers and union types that span several lines are joined, multi-line method parameters are joined
  up to the closing parenthesis, signatures are cut at 220 characters.

## Counts

- CLASS: 256
- USEDBY: 44
- METHOD: 430
- PROPERTY: 852
- ENUM: 42
- TYPE: 85

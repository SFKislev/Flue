#!/usr/bin/env python3
"""Build docs/api-index.txt from Figma's official plugin typings (plugin-api.d.ts).

    npm pack @figma/plugin-typings@<version> && tar xzf figma-plugin-typings-*.tgz
    python extract_api_index.py package/plugin-api.d.ts > api-index.txt

Symbol names and short signatures only (no prose), grep-friendly, tab separated:
    CLASS     Name  [extends A, B]
    USEDBY    Mixin  Node,Node,...        (which node types get this mixin's members)
    METHOD    Owner.name(params): ret     (`figma.` for the global API object and its sub-APIs)
    PROPERTY  Owner.name: type
    ENUM      Name  A|B|C                 (string-literal unions)
    TYPE      Name                        (other aliases)
"""

import re
import sys
from collections import OrderedDict

MAX_SIG = 220


def parse(text):
    interfaces = OrderedDict()  # name -> {"extends": [...], "members": [(kind, text)]}
    aliases = OrderedDict()  # name -> body text
    lines = text.splitlines()
    cur = None
    in_comment = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        i += 1
        if in_comment:
            if "*/" in stripped:
                in_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_comment = True
            continue
        if stripped.startswith("//"):
            continue
        if cur is None:
            if re.match(r"^(?:declare\s+)?interface\s+\w+", line):
                # headers can span lines: `interface X` / `  extends A, B {`
                header = line.strip()
                while "{" not in header and i < len(lines):
                    header += " " + lines[i].strip()
                    i += 1
                m = re.match(r"^(?:declare\s+)?interface\s+(\w+)(?:<[^>{]*>)?(?:\s+extends\s+(.+?))?\s*\{(.*)$", header)
                if not m:
                    continue
                name = m.group(1)
                ext = [e.strip().split("<")[0] for e in (m.group(2) or "").split(",") if e.strip()]
                interfaces.setdefault(name, {"extends": [], "members": []})["extends"] += ext
                cur = None if m.group(3).strip().startswith("}") else name
                continue
            m = re.match(r"^(?:declare\s+)?type\s+(\w+)(?:<[^>=]*>)?\s*=\s*(.*)$", line)
            if m:
                body = [m.group(2)]
                while i < len(lines) and lines[i].startswith((" ", "\t", "|")) and len(body) < 60:
                    body.append(lines[i].strip())
                    i += 1
                aliases[m.group(1)] = " ".join(b for b in body if b)
            continue
        if line.startswith("}"):
            cur = None
            continue
        m = re.match(r"^  (readonly\s+)?([A-Za-z_$][\w$]*)(\??)\s*(\(|:|<)", line)
        if not m:
            continue
        readonly, name, opt, sep = m.groups()
        rest = line.strip()
        # union types often continue on the following lines: `prop:` / `| 'A'` / `| 'B'`
        extra = 0
        while i < len(lines) and extra < 12:
            nxt = lines[i].strip()
            if nxt and not nxt.startswith(("/*", "*", "//")) and (rest.endswith((":", "|")) or nxt.startswith("|")):
                rest += " " + nxt
                i += 1
                extra += 1
            else:
                break
        if rest.endswith("("):  # parameters on following lines: join up to the closing line
            extra = 0
            while i < len(lines) and extra < 14:
                nxt = lines[i].strip()
                rest += " " + nxt
                i += 1
                extra += 1
                if nxt.startswith(")"):
                    break
            rest = re.sub(r",\s*\)", ")", re.sub(r"\(\s+", "(", re.sub(r"\s+", " ", rest)))
        if len(rest) > MAX_SIG:
            rest = rest[: MAX_SIG - 1] + "…"
        kind = "METHOD" if sep in ("(", "<") else "PROPERTY"
        interfaces[cur]["members"].append((kind, rest, name))
    return interfaces, aliases


def closure(interfaces, name, seen=None):
    seen = seen if seen is not None else set()
    for base in interfaces.get(name, {}).get("extends", []):
        if base not in seen:
            seen.add(base)
            closure(interfaces, base, seen)
    return seen


def main(path):
    text = open(path, encoding="utf-8").read()
    interfaces, aliases = parse(text)

    # Sub-APIs hang off the global: `readonly variables: VariablesAPI` => figma.variables.*
    prefix = {"PluginAPI": "figma"}
    for kind, sig, name in interfaces.get("PluginAPI", {}).get("members", []):
        m = re.match(rf"^(?:readonly\s+)?{re.escape(name)}\??:\s*(\w+)$", sig)
        if kind == "PROPERTY" and m and m.group(1) in interfaces and m.group(1).endswith("API"):
            prefix[m.group(1)] = f"figma.{name}"

    out = [
        "# Figma Plugin API Index (grep-friendly)",
        "# Source: @figma/plugin-typings plugin-api.d.ts (MIT). See sources.md.",
        "# Format: KIND<TAB>symbol. Search with rg before writing a script; do not read this file whole.",
        "# Properties live on mixins: use USEDBY lines to see which node types have them.",
        "",
        "# CLASS",
    ]
    for name, info in interfaces.items():
        if name == "PluginAPI":
            continue
        out.append(f"CLASS\t{name}" + (f"\textends {', '.join(info['extends'])}" if info["extends"] else ""))

    out += ["", "# USEDBY (mixin -> node types)"]
    nodes = [n for n in interfaces if n.endswith("Node")]
    users = OrderedDict()
    for n in nodes:
        for base in closure(interfaces, n):
            if base.endswith("Mixin"):
                users.setdefault(base, []).append(n)
    for mixin, ns in users.items():
        out.append(f"USEDBY\t{mixin}\t{','.join(sorted(ns))}")

    out += ["", "# MEMBERS"]
    for name, info in interfaces.items():
        owner = prefix.get(name, name)
        for kind, sig, member in info["members"]:
            out.append(f"{kind}\t{owner}.{sig}")

    out += ["", "# ENUM / TYPE"]
    for name, body in aliases.items():
        lits = re.findall(r"'([^']+)'", body)
        only_literals = lits and re.fullmatch(r"[\s|']*(?:[\w:/ .\-]+[\s|']*)*", body) and "{" not in body and "(" not in body
        if only_literals and len(lits) >= 2 and all(re.fullmatch(r"\s*\|?\s*'[^']+'\s*", p) for p in body.split("|") if p.strip()):
            out.append(f"ENUM\t{name}\t{'|'.join(lits)}")
        else:
            out.append(f"TYPE\t{name}")
    print("\n".join(out))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

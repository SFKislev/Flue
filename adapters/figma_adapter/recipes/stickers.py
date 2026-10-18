"""Sticker-style shapes for `figma_bridge.py build`: flat blobs, starbursts, pills and tilted lettering.

Build specs are plain JSON, so the cheapest way to design in Figma is a small script that *generates* the spec
and pipes it in. The spec never comes back into the agent's context; only the short result does.

    python adapters/figma_adapter/recipes/stickers.py | python adapters/figma_adapter/figma_bridge.py build --stdin

Import it from your own generator:   sys.path.insert(0, "adapters/figma_adapter/recipes"); from stickers import *
Shapes are inline SVG (`{"t":"svg"}`), text sits in an auto-layout overlay so it stays centred.
Pick text colours that contrast with the shape (PAIRS gives tested combinations).
"""

import json
import math
import random
import sys

PINK, RED, GREEN, BLUE, ORANGE, PEACH, SKY = "#f8b4e2", "#ee2a24", "#0f7a3c", "#1672d8", "#f5994a", "#f8c58d", "#90e2f6"
# (shape colour, text colour) pairs that read well together
PAIRS = [(PINK, RED), (RED, PINK), (GREEN, PEACH), (BLUE, PEACH), (ORANGE, BLUE), (SKY, BLUE), (PEACH, BLUE), (BLUE, PINK), (GREEN, ORANGE)]
FONT = "Fredoka"  # any installed family; run `figma_bridge.py eval` with figma.listAvailableFontsAsync() to check


def text(t, size=14, weight=700, fill="#ffffff", **kw):
    return dict(t="text", text=t, size=size, weight=weight, fill=fill, font=FONT, **kw)


def _svg(w, h, body):
    return f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{body}</svg>"


def _smooth(pts):
    """Closed Catmull-Rom spline through pts as cubic beziers."""
    n, d = len(pts), f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(n):
        p0, p1, p2, p3 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d + "Z"


def shape_svg(shape, w, h, color, seed=1):
    """shape: blob | burst | tri | dome | pill | rect | ell"""
    rnd, sw, cx, cy = random.Random(seed), 10, w / 2, h / 2
    rounded = f"stroke='{color}' stroke-width='{sw}' stroke-linejoin='round'"  # same-colour stroke rounds polygon corners
    if shape == "blob":
        n, pts = 9, []
        for i in range(n):
            a, r = 2 * math.pi * i / n + rnd.uniform(-.12, .12), 1 + rnd.uniform(-.16, .12)
            pts.append((cx + math.cos(a) * (w / 2 - 3) * r * .93, cy + math.sin(a) * (h / 2 - 3) * r * .93))
        return _svg(w, h, f"<path d='{_smooth(pts)}' fill='{color}'/>")
    if shape == "burst":
        n = rnd.choice([10, 12, 14])
        pts = [(cx + math.cos(math.pi * i / n) * (w / 2 - sw) * (1 if i % 2 == 0 else .76),
                cy + math.sin(math.pi * i / n) * (h / 2 - sw) * (1 if i % 2 == 0 else .76)) for i in range(n * 2)]
        return _svg(w, h, f"<path d='M{' L'.join(f'{x:.1f},{y:.1f}' for x, y in pts)}Z' fill='{color}' {rounded}/>")
    if shape == "tri":
        return _svg(w, h, f"<path d='M{cx},{sw} L{w - sw},{h - sw} L{sw},{h - sw}Z' fill='{color}' {rounded}/>")
    if shape == "dome":
        r = (w - 2 * sw) / 2
        return _svg(w, h, f"<path d='M{sw},{h - sw} L{sw},{sw + r} A{r},{r} 0 0 1 {w - sw},{sw + r} L{w - sw},{h - sw}Z' fill='{color}' {rounded}/>")
    if shape == "pill":
        return _svg(w, h, f"<rect width='{w}' height='{h}' rx='{h / 2}' fill='{color}'/>")
    if shape == "rect":
        return _svg(w, h, f"<rect width='{w}' height='{h}' rx='{min(22, h / 3)}' fill='{color}'/>")
    if shape == "ell":
        return _svg(w, h, f"<ellipse cx='{cx}' cy='{cy}' rx='{w / 2}' ry='{h / 2}' fill='{color}'/>")
    raise ValueError(f"unknown shape {shape}")


def sticker(w, h, shape, color, lines=None, tc=RED, rot=0, trot=0, seed=1, name="Sticker", extra=None, x=None, y=None):
    """A shape with centred text. lines: "TEXT" or [(text, size), ...]. extra: more child nodes at x,y inside the shape."""
    kids = [dict(t="svg", name="Shape", x=0, y=0, svg=shape_svg(shape, w, h, color, seed))] + list(extra or [])
    if lines:
        if isinstance(lines, str):
            lines = [(lines, 20)]
        kids.append(dict(t="frame", name="Label", w=w, h=h, layout="v", main="center", cross="center", rot=trot,
                         c=[text(t, s, 700, tc, ta="center", lh="95%") for t, s in lines]))
    node = dict(t="frame", name=name, w=w, h=h, rot=rot, c=kids)
    if x is not None:
        node.update(x=x, y=y)
    return node


def row(children, gap=-10, **kw):  # negative gaps overlap stickers, which is the look
    return dict(t="frame", layout="h", gap=gap, cross="center", c=children, **kw)


def col(children, gap=-10, **kw):
    return dict(t="frame", layout="v", gap=gap, cross="center", c=children, **kw)


def screen(name, children, x=0, y=0, w=390, h=844, bg="#000000", main="start"):
    return dict(t="frame", name=name, x=x, y=y, w=w, h=h, layout="v", main=main, fill=bg, clip=True, c=children)


if __name__ == "__main__":  # demo: a small sheet of stickers
    demo = screen("Sticker demo", [
        col([sticker(270, 118, "blob", PINK, [("HELLO", 60)], RED, rot=-5, seed=2),
             row([sticker(176, 156, "burst", SKY, [("FROM", 48)], BLUE, rot=6, seed=4), sticker(96, 128, "ell", RED, [("!", 76)], PINK, rot=-10)], gap=-14)],
            gap=-16, pad=[40, 0, 0, 0], w="fill"),
        sticker(344, 80, "blob", ORANGE, [("FLUE", 34)], BLUE, rot=-1.5, seed=7),
    ])
    json.dump({"nodes": [demo]}, sys.stdout)

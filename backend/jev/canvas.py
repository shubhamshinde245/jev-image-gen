"""Canvas grid helpers: cells, RGB blend, sketch, and artifact writers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from jev.palette import LETTER, PALETTE

SHARPEN = 3.0  # >1 lets agreeing repeat answers out-vote one bad answer

Cell = dict[str, Any]
Grid = list[list[Cell]]


def cell(probs: dict[str, float] | None = None) -> Cell:
    return {"probs": probs or {}, "n": 1 if probs else 0}


def choice_of(c: Cell) -> str:
    return max(c["probs"], key=c["probs"].get) if c["probs"] else "?"


def sharp(probs: dict[str, float]) -> dict[str, float]:
    """Temperature-sharpen an averaged distribution (p^k, renormalised)."""
    w = {k: v**SHARPEN for k, v in probs.items()}
    s = sum(w.values()) or 1.0
    return {k: v / s for k, v in w.items()}


def conf_of(c: Cell) -> float:
    return max(sharp(c["probs"]).values()) if c["probs"] else 0.0


def rgb_of(c: Cell) -> tuple[int, int, int]:
    if not c["probs"]:
        return (128, 128, 128)
    r = g = b = 0.0
    for name, p in sharp(c["probs"]).items():
        cr, cg, cb = PALETTE.get(name, (0, 0, 0))
        r, g, b = r + p * cr, g + p * cg, b + p * cb
    return (int(r), int(g), int(b))


def merge(c: Cell, probs: dict[str, float]) -> Cell:
    """Running average of probability distributions across attempts."""
    if not c["probs"]:
        return {"probs": dict(probs), "n": 1}
    n = c["n"]
    avg = {k: (c["probs"].get(k, 0) * n + probs.get(k, 0)) / (n + 1) for k in PALETTE}
    return {"probs": avg, "n": n + 1}


def sketch(grid: Grid, size: int, cols: int = 32) -> str:
    """ASCII sketch of the current canvas, fed back into the state."""
    step = max(1, size // cols)
    rows = [
        "".join(LETTER.get(choice_of(grid[y][x]), "?") for x in range(0, size, step))
        for y in range(0, size, step)
    ]
    legend = ", ".join(f"{v}={k}" for k, v in LETTER.items())
    return (
        f"Current low-resolution sketch ({legend}; ? = unknown; "
        f"row 0 is the top, column 0 is the left):\n" + "\n".join(rows)
    )


def save_png(grid: Grid, size: int, path: Path | str, scale: int = 8) -> None:
    path = Path(path)
    img = Image.new("RGB", (size, size))
    img.putdata([rgb_of(grid[y][x]) for y in range(size) for x in range(size)])
    img.resize((size * scale, size * scale), Image.NEAREST).save(path)


def save_canvas_html(grid: Grid, size: int, path: Path | str) -> None:
    path = Path(path)
    flat = [c for y in range(size) for x in range(size) for c in (*rgb_of(grid[y][x]), 255)]
    html = f"""<!doctype html><meta charset=utf-8><title>Jev canvas</title>
<style>body{{background:#111;display:grid;place-items:center;height:100vh;margin:0}}
canvas{{width:min(90vw,512px);image-rendering:pixelated}}</style>
<canvas id=c width={size} height={size}></canvas><script>
const d=new Uint8ClampedArray({json.dumps(flat)});
document.getElementById('c').getContext('2d').putImageData(new ImageData(d,{size},{size}),0,0);
</script>"""
    path.write_text(html)

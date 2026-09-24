"""Generation modes, quality loop, and refine for Jev pixel generation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from jev.canvas import (
    Grid,
    cell,
    choice_of,
    conf_of,
    merge,
    save_canvas_html,
    save_png,
    sketch,
)
from jev.client import Asker, truth
from jev.questions import colour_q, flat_q, pbox, scene_elements

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


async def run_single(scene: str, size: int, asker: Asker) -> tuple[Grid, int]:
    grid = [[cell() for _ in range(size)] for _ in range(size)]
    qs = {f"p_{x}_{y}": colour_q(pbox(x, y, size)) for y in range(size) for x in range(size)}
    ans = await asker(f"Canvas description:\n{scene}", qs)
    for qid, a in ans.items():
        _, x, y = qid.split("_")
        grid[int(y)][int(x)] = cell(a["probabilities"])
    return grid, len(qs)


async def run_multi(
    scene: str,
    size: int,
    asker: Asker,
    *,
    start_blocks: int = 8,
    flat_thr: float = 0.8,
    conf_thr: float = 0.8,
) -> tuple[Grid, int]:
    grid = [[cell() for _ in range(size)] for _ in range(size)]
    bs = max(1, size // start_blocks)
    cells = [(x, y, bs) for y in range(0, size, bs) for x in range(0, size, bs)]
    passno, total_q = 0, 0
    while cells:
        passno += 1
        state = f"Canvas description:\n{scene}"
        if passno > 1:
            state += "\n\n" + sketch(grid, size)
        qs: dict[str, Any] = {}
        for i, (x, y, s) in enumerate(cells):
            box = (x / size, y / size, (x + s) / size, (y + s) / size)
            qs[f"c{i}"] = colour_q(box)
            if s > 1:
                qs[f"f{i}"] = flat_q(box)
        total_q += len(qs)
        ans = await asker(state, qs)

        nxt: list[tuple[int, int, int]] = []
        for i, (x, y, s) in enumerate(cells):
            a = ans[f"c{i}"]
            for yy in range(y, y + s):
                for xx in range(x, x + s):
                    grid[yy][xx] = cell(a["probabilities"])
            flat = ans.get(f"f{i}", {}).get("noul", 1.0)
            if s > 1 and not (flat >= flat_thr and a.get("confidence", 0) >= conf_thr):
                h = s // 2
                nxt += [(x, y, h), (x + h, y, h), (x, y + h, h), (x + h, y + h, h)]
        cells = nxt
    return grid, total_q


async def critique(
    scene: str, grid: Grid, size: int, asker: Asker
) -> tuple[float, list[str]]:
    """Returns (critic_score 0-1, list of scene elements judged as failed)."""
    elements = scene_elements(scene)
    if getattr(asker, "is_mock", False):
        right = total = 0
        for y in range(size):
            for x in range(size):
                t = truth((x + 0.5) / size, (y + 0.5) / size)
                right += choice_of(grid[y][x]) == t
                total += 1
        return right / total, []

    state = f"Intended scene:\n{scene}\n\n{sketch(grid, size, cols=min(size, 64))}"
    qs: dict[str, Any] = {
        f"e{i}": {
            "type": "noul",
            "instructions": f"The sketch correctly depicts this part of the intended scene: {el}",
        }
        for i, el in enumerate(elements)
    }
    qs["overall"] = {
        "type": "score",
        "instructions": "How faithfully the sketch matches the whole intended scene",
        "criteria": [
            "Unrecognisable",
            "Major parts wrong or missing",
            "Recognisable with noticeable errors",
            "Minor errors only",
            "Matches exactly",
        ],
    }
    ans = await asker(state, qs)
    nouls = [ans[f"e{i}"]["noul"] for i in range(len(elements))]
    overall = ans["overall"]["score"] / 4.0
    failed = [el for el, v in zip(elements, nouls) if v < 0.5]
    score = 0.5 * (sum(nouls) / max(1, len(nouls))) + 0.5 * overall
    return score, failed


async def measure(
    scene: str,
    grid: Grid,
    size: int,
    asker: Asker,
    *,
    w_conf: float = 0.4,
    w_crit: float = 0.6,
) -> tuple[float, float, float, list[str]]:
    mean_conf = sum(conf_of(grid[y][x]) for y in range(size) for x in range(size)) / (size * size)
    crit, failed = await critique(scene, grid, size, asker)
    return w_conf * mean_conf + w_crit * crit, mean_conf, crit, failed


def suspects(grid: Grid, size: int, conf_thr: float) -> set[tuple[int, int]]:
    """Pixels to re-ask: low confidence, or out-voted by their 8 neighbours."""
    out: set[tuple[int, int]] = set()
    for y in range(size):
        for x in range(size):
            c = grid[y][x]
            if conf_of(c) < conf_thr:
                out.add((x, y))
                continue
            me, same, n = choice_of(c), 0, 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if (dx or dy) and 0 <= x + dx < size and 0 <= y + dy < size:
                        n += 1
                        same += choice_of(grid[y + dy][x + dx]) == me
            if n and same <= 1:
                out.add((x, y))
    return out


async def refine(
    scene: str,
    grid: Grid,
    size: int,
    asker: Asker,
    targets: set[tuple[int, int]],
    failed: list[str],
) -> int:
    state = f"Canvas description:\n{scene}\n\n{sketch(grid, size)}"
    if failed:
        state += (
            "\n\nA reviewer found these parts are NOT yet drawn correctly; "
            "pay special attention to them:\n- " + "\n- ".join(failed)
        )
    qs = {f"p_{x}_{y}": colour_q(pbox(x, y, size)) for (x, y) in targets}
    ans = await asker(state, qs)
    for qid, a in ans.items():
        _, x, y = qid.split("_")
        x, y = int(x), int(y)
        grid[y][x] = merge(grid[y][x], a["probabilities"])
    return len(qs)


async def generate(
    scene: str,
    size: int,
    mode: str,
    asker: Asker,
    out_dir: Path,
    *,
    max_iters: int = 5,
    target: float = 0.9,
    conf_thr: float = 0.8,
    on_progress: ProgressCallback | None = None,
) -> tuple[tuple[float, Grid, int], list[dict[str, Any]]]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    best: tuple[float, Grid, int] | None = None
    grid, q = await (run_single if mode == "single" else run_multi)(scene, size, asker)
    failed: list[str] = []

    for it in range(1, max_iters + 1):
        if it > 1:
            targets = suspects(grid, size, conf_thr)
            if not targets and not failed:
                break
            if failed and len(targets) < size:
                targets |= {
                    (x, y)
                    for y in range(size)
                    for x in range(size)
                    if conf_of(grid[y][x]) < min(0.95, conf_thr + 0.1)
                }
            q = await refine(scene, grid, size, asker, targets, failed)

        quality, mean_conf, crit, failed = await measure(scene, grid, size, asker)
        save_png(grid, size, out_dir / f"iter_{it}.png")
        rec = {
            "iter": it,
            "questions": q,
            "quality": round(quality, 4),
            "mean_confidence": round(mean_conf, 4),
            "critic": round(crit, 4),
            "failed_elements": failed,
        }
        history.append(rec)
        if on_progress:
            maybe = on_progress({**rec, "status": "running"})
            if maybe is not None:
                await maybe

        if best is None or quality > best[0]:
            best = (quality, [[dict(c) for c in row] for row in grid], it)
        if quality >= target:
            break

    assert best is not None
    quality, best_grid, best_it = best
    save_png(best_grid, size, out_dir / "final.png")
    save_canvas_html(best_grid, size, out_dir / "canvas.html")
    (out_dir / "quality.json").write_text(json.dumps(history, indent=2))
    return (quality, best_grid, best_it), history

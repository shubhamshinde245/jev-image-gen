"""Question builders and scene element parsing for Jev pixel generation."""

from __future__ import annotations

import re
from typing import Any

from jev.palette import PALETTE

Box = tuple[float, float, float, float]
Question = dict[str, Any]


def fmt(v: float) -> str:
    return f"{v:.3f}"


def colour_q(box: Box) -> Question:
    x0, y0, x1, y1 = box
    return {
        "type": "choice",
        "instructions": (
            f"Which colour covers most of the region x from {fmt(x0)} to {fmt(x1)}, "
            f"y from {fmt(y0)} to {fmt(y1)} (normalised coords, origin top-left, y grows down)?"
        ),
        "criteria": {c: f"The region is mostly {c}" for c in PALETTE},
        "_box": box,
    }


def flat_q(box: Box) -> Question:
    x0, y0, x1, y1 = box
    return {
        "type": "noul",
        "instructions": (
            f"The region x from {fmt(x0)} to {fmt(x1)}, y from {fmt(y0)} to {fmt(y1)} "
            "is entirely one colour: no shape edge or outline passes through it."
        ),
        "_box": box,
    }


def strip_private(qs: dict[str, Question]) -> dict[str, Question]:
    return {k: {kk: vv for kk, vv in q.items() if not kk.startswith("_")} for k, q in qs.items()}


def scene_elements(scene: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", scene) if s.strip()]


def pbox(x: int, y: int, size: int) -> Box:
    return (x / size, y / size, (x + 1) / size, (y + 1) / size)

"""Async TypeSafe asker and mock oracle for Jev pixel generation."""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

from jev.palette import PALETTE
from jev.questions import Question, strip_private

BATCH = int(os.getenv("JEV_BATCH", "200"))
WORKERS = int(os.getenv("JEV_WORKERS", "8"))

Answer = dict[str, Any]
Asker = Callable[[str, dict[str, Question]], Awaitable[dict[str, Answer]]]


def truth(u: float, v: float) -> str:
    """Ground truth for DEFAULT_SCENE in normalised coords (used by --mock)."""
    if 0.20 <= u <= 0.50 and 0.45 <= v <= 0.75:
        if 0.31 <= u <= 0.39 and v >= 0.60:
            return "blue"
        if u < 0.22 or u > 0.48 or v < 0.47:
            return "black"
        return "red"
    if v > 0.75:
        return "green"
    if (u - 0.78) ** 2 + (v - 0.22) ** 2 <= 0.14**2:
        return "yellow"
    return "white"


def make_mock(noise: float) -> Asker:
    """Mock Jev: samples the true scene; with prob `noise` answers wrongly."""

    async def mock_ask(state: str, questions: dict[str, Question]) -> dict[str, Answer]:
        _ = state
        out: dict[str, Answer] = {}
        n = 4
        for qid, q in questions.items():
            if q["type"] == "critic":
                continue
            x0, y0, x1, y1 = q["_box"]
            counts: dict[str, int] = {}
            for _ in range(n * n):
                c = truth(random.uniform(x0, x1), random.uniform(y0, y1))
                counts[c] = counts.get(c, 0) + 1
            total = sum(counts.values())
            probs = {k: counts.get(k, 0) / total for k in PALETTE}
            if q["type"] == "noul":
                out[qid] = {"type": "noul", "noul": 1.0 if max(probs.values()) == 1 else 0.0}
                continue
            if random.random() < noise:
                wrong = random.choice(list(PALETTE))
                c = random.uniform(0.3, 0.75)
                probs = {k: (c if k == wrong else (1 - c) / (len(PALETTE) - 1)) for k in PALETTE}
            best = max(probs, key=probs.get)
            out[qid] = {
                "type": "choice",
                "choice": best,
                "probabilities": probs,
                "confidence": probs[best],
            }
        return out

    mock_ask.is_mock = True  # type: ignore[attr-defined]
    return mock_ask


def _to_sdk_questions(
    questions: Mapping[str, Question],
) -> dict[str, Choice | Noul | Score]:
    out: dict[str, Choice | Noul | Score] = {}
    for qid, q in strip_private(dict(questions)).items():
        qtype = q["type"]
        if qtype == "choice":
            out[qid] = Choice(instructions=q["instructions"], criteria=q["criteria"])
        elif qtype == "noul":
            out[qid] = Noul(instructions=q["instructions"])
        elif qtype == "score":
            out[qid] = Score(instructions=q["instructions"], criteria=q["criteria"])
        else:
            raise ValueError(f"unsupported question type: {qtype}")
    return out


def _answers_from_response(response: Any, question_ids: list[str]) -> dict[str, Answer]:
    out: dict[str, Answer] = {}
    for qid in question_ids:
        if qid in response.choices:
            a = response.choices[qid]
            out[qid] = {
                "type": "choice",
                "choice": a.choice,
                "probabilities": dict(a.probabilities),
                "confidence": a.confidence,
            }
        elif qid in response.nouls:
            a = response.nouls[qid]
            out[qid] = {"type": "noul", "noul": a.noul}
        elif qid in response.scores:
            a = response.scores[qid]
            out[qid] = {"type": "score", "score": a.score}
        else:
            raise KeyError(f"missing answer for question {qid!r}")
    return out


def make_sdk_asker(client: AsyncTypeSafeClient, *, model: str | None = "jev-latest") -> Asker:
    """Chunked, concurrent system_one asks via AsyncTypeSafeClient."""
    sem = asyncio.Semaphore(WORKERS)

    async def ask(state: str, questions: dict[str, Question]) -> dict[str, Answer]:
        items = list(questions.items())
        chunks = [dict(items[i : i + BATCH]) for i in range(0, len(items), BATCH)]

        async def one_chunk(chunk: dict[str, Question]) -> dict[str, Answer]:
            async with sem:
                response = await client.system_one(
                    state={"document": state},
                    questions=_to_sdk_questions(chunk),
                    model=model,
                )
                return _answers_from_response(response, list(chunk.keys()))

        parts = await asyncio.gather(*(one_chunk(c) for c in chunks))
        out: dict[str, Answer] = {}
        for part in parts:
            out.update(part)
        return out

    ask.is_mock = False  # type: ignore[attr-defined]
    return ask

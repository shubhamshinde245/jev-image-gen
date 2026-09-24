"""In-memory async job store for Jev pixel generation."""

from __future__ import annotations

import asyncio
import random
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from typesafe_sdk import AsyncTypeSafeClient

from jev.client import make_mock, make_sdk_asker
from jev.generate import generate
from jev.palette import DEFAULT_SCENE

JobStatus = Literal["queued", "running", "done", "error"]

OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"
MAX_SIZE = 128


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus = "queued"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    params: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "params": self.params,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "artifacts": self.artifacts,
        }


class JobStore:
    def __init__(self, outputs_dir: Path = OUTPUTS_DIR) -> None:
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobRecord] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def job_dir(self, job_id: str) -> Path:
        return self.outputs_dir / job_id

    def list_artifacts(self, job_id: str) -> list[str]:
        d = self.job_dir(job_id)
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_file())

    async def start(
        self,
        *,
        client: AsyncTypeSafeClient | None,
        scene: str = DEFAULT_SCENE,
        mode: str = "multi",
        size: int = 64,
        max_iters: int = 5,
        target: float = 0.9,
        conf_thr: float = 0.8,
        mock: bool = False,
        mock_noise: float = 0.15,
        seed: int | None = None,
    ) -> JobRecord:
        if size < 1 or size > MAX_SIZE or size & (size - 1):
            raise ValueError(f"size must be a power of 2 between 1 and {MAX_SIZE}")
        if mode not in ("single", "multi"):
            raise ValueError("mode must be 'single' or 'multi'")
        if max_iters < 1:
            raise ValueError("max_iters must be >= 1")
        if not mock and client is None:
            raise ValueError("TYPESAFE client required when mock=false")

        job_id = uuid.uuid4().hex[:12]
        params = {
            "scene": scene,
            "mode": mode,
            "size": size,
            "max_iters": max_iters,
            "target": target,
            "conf_thr": conf_thr,
            "mock": mock,
            "mock_noise": mock_noise,
            "seed": seed,
        }
        record = JobRecord(job_id=job_id, params=params)
        async with self._lock:
            self._jobs[job_id] = record
            task = asyncio.create_task(self._run(record, client), name=f"jev-job-{job_id}")
            self._tasks[job_id] = task
        return record

    async def _run(self, record: JobRecord, client: AsyncTypeSafeClient | None) -> None:
        p = record.params
        out_dir = self.job_dir(record.job_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        record.status = "running"
        record.touch()

        if p["seed"] is not None:
            random.seed(p["seed"])

        asker = make_mock(p["mock_noise"]) if p["mock"] else make_sdk_asker(client)  # type: ignore[arg-type]

        async def on_progress(rec: dict[str, Any]) -> None:
            record.progress = {
                "iter": rec["iter"],
                "questions": rec["questions"],
                "quality": rec["quality"],
                "mean_confidence": rec["mean_confidence"],
                "critic": rec["critic"],
                "failed_elements": rec["failed_elements"],
            }
            record.artifacts = self.list_artifacts(record.job_id)
            record.touch()

        try:
            (quality, _grid, best_it), history = await generate(
                p["scene"],
                p["size"],
                p["mode"],
                asker,
                out_dir,
                max_iters=p["max_iters"],
                target=p["target"],
                conf_thr=p["conf_thr"],
                on_progress=on_progress,
            )
            record.status = "done"
            record.result = {
                "best_iter": best_it,
                "quality": round(quality, 4),
                "history": history,
            }
            record.artifacts = self.list_artifacts(record.job_id)
            record.progress = history[-1] if history else None
            record.touch()
        except Exception as exc:
            record.status = "error"
            record.error = f"{exc}\n{traceback.format_exc()}"
            record.touch()


job_store = JobStore()

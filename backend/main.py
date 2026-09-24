import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

from jev.jobs import MAX_SIZE, job_store
from jev.palette import DEFAULT_SCENE

_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env.local")
load_dotenv(_BACKEND_DIR / ".env")

_ARTIFACT_RE = re.compile(r"^(final\.png|canvas\.html|quality\.json|iter_\d+\.png)$")


class AnalyzeRequest(BaseModel):
    document: str = Field(..., min_length=1, description="Ticket or message text to analyze")


class AnalyzeResponse(BaseModel):
    billing: float  # P(yes) for the billing noul
    tone: str
    urgency: float  # expected score (may fall between rubric levels)


class GenerateRequest(BaseModel):
    scene: str = Field(default=DEFAULT_SCENE, min_length=1)
    mode: Literal["single", "multi"] = "multi"
    size: int = Field(default=64, ge=1, le=MAX_SIZE)
    max_iters: int = Field(default=5, ge=1, le=20)
    target: float = Field(default=0.9, ge=0.0, le=1.0)
    conf_thr: float = Field(default=0.8, ge=0.0, le=1.0)
    mock: bool = False
    mock_noise: float = Field(default=0.15, ge=0.0, le=1.0)
    seed: int | None = None

    @field_validator("size")
    @classmethod
    def power_of_two(cls, v: int) -> int:
        if v & (v - 1):
            raise ValueError("size must be a power of 2")
        return v


class GenerateResponse(BaseModel):
    job_id: str
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    api_key = os.getenv("TYPESAFE_API_KEY")
    app.state.client = AsyncTypeSafeClient() if api_key else None
    yield
    client = getattr(app.state, "client", None)
    if client is not None:
        await client.aclose()


app = FastAPI(title="jev-image-gen", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    client: AsyncTypeSafeClient | None = app.state.client
    if client is None:
        raise HTTPException(status_code=503, detail="TYPESAFE_API_KEY is not set")
    try:
        response = await client.system_one(
            state={"document": body.document},
            questions={
                "billing": Noul(instructions="Is this ticket about billing?"),
                "tone": Choice(
                    instructions="What is the customer's tone?",
                    criteria={"calm": None, "frustrated": None, "angry": None},
                ),
                "urgency": Score(
                    instructions="How urgent is this ticket?",
                    criteria=["can wait", "this week", "today"],
                ),
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AnalyzeResponse(
        billing=response.nouls["billing"].noul,
        tone=response.choices["tone"].choice,
        urgency=response.scores["urgency"].score,
    )


@app.post("/generate", response_model=GenerateResponse)
async def start_generate(body: GenerateRequest) -> GenerateResponse:
    if not body.mock and app.state.client is None:
        raise HTTPException(status_code=503, detail="TYPESAFE_API_KEY is not set (or use mock=true)")
    try:
        record = await job_store.start(
            client=app.state.client,
            scene=body.scene,
            mode=body.mode,
            size=body.size,
            max_iters=body.max_iters,
            target=body.target,
            conf_thr=body.conf_thr,
            mock=body.mock,
            mock_noise=body.mock_noise,
            seed=body.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GenerateResponse(job_id=record.job_id, status=record.status)


@app.get("/generate/{job_id}")
async def get_generate(job_id: str) -> dict[str, Any]:
    record = job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    data = record.to_dict()
    data["artifacts"] = job_store.list_artifacts(job_id)
    return data


@app.get("/generate/{job_id}/artifacts/{name}")
async def get_artifact(job_id: str, name: str) -> FileResponse:
    if job_store.get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not _ARTIFACT_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid artifact name")
    path = job_store.job_dir(job_id) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    media = {
        ".png": "image/png",
        ".html": "text/html",
        ".json": "application/json",
    }.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=name)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "jev-image-gen",
        "endpoints": {
            "POST /analyze": "Analyze a support ticket document",
            "POST /generate": "Start a Jev pixel-generation job",
            "GET /generate/{job_id}": "Poll job status",
            "GET /generate/{job_id}/artifacts/{name}": "Download an artifact",
        },
    }

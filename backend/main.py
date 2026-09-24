import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env.local")
load_dotenv(_BACKEND_DIR / ".env")


class AnalyzeRequest(BaseModel):
    document: str = Field(..., min_length=1, description="Ticket or message text to analyze")


class AnalyzeResponse(BaseModel):
    billing: float  # P(yes) for the billing noul
    tone: str
    urgency: float  # expected score (may fall between rubric levels)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("TYPESAFE_API_KEY"):
        raise RuntimeError("TYPESAFE_API_KEY is not set (check .env.local)")
    app.state.client = AsyncTypeSafeClient()
    yield
    await app.state.client.aclose()


app = FastAPI(title="jev-image-gen", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    client: AsyncTypeSafeClient = app.state.client
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


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "jev-image-gen",
        "endpoints": {"POST /analyze": "Analyze a support ticket document"},
    }

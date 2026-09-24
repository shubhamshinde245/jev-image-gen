"""Live API tests. These call the real TypeSafe API; nothing is mocked."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    if not os.getenv("TYPESAFE_API_KEY"):
        pytest.fail("TYPESAFE_API_KEY is not set (backend/.env.local)")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=120.0) as http:
            yield http


async def wait_for_job(client: AsyncClient, job_id: str, *, timeout_s: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        res = await client.get(f"/generate/{job_id}")
        assert res.status_code == 200, res.text
        last = res.json()
        if last["status"] in ("done", "error"):
            return last
        await asyncio.sleep(0.5)
    pytest.fail(f"job {job_id} did not finish; last={last}")


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_root_lists_endpoints(client: AsyncClient) -> None:
    res = await client.get("/")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "jev-image-gen"
    assert "POST /analyze" in body["endpoints"]
    assert "POST /generate" in body["endpoints"]


@pytest.mark.asyncio
async def test_analyze_live(client: AsyncClient) -> None:
    res = await client.post(
        "/analyze",
        json={"document": "I was charged twice. Please fix this ASAP."},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["billing"], float)
    assert 0.0 <= body["billing"] <= 1.0
    assert body["tone"] in {"calm", "frustrated", "angry"}
    assert isinstance(body["urgency"], float)
    assert 0.0 <= body["urgency"] <= 2.0


@pytest.mark.asyncio
async def test_analyze_rejects_empty_document(client: AsyncClient) -> None:
    res = await client.post("/analyze", json={"document": ""})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_generate_rejects_non_power_of_two(client: AsyncClient) -> None:
    res = await client.post("/generate", json={"size": 12, "max_iters": 1})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_generate_unknown_job(client: AsyncClient) -> None:
    res = await client.get("/generate/does-not-exist")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_generate_live_job_and_artifacts(client: AsyncClient) -> None:
    res = await client.post(
        "/generate",
        json={
            "scene": "White background. A red square in the centre.",
            "mode": "single",
            "size": 4,
            "max_iters": 1,
            "target": 0.0,
        },
    )
    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]
    assert res.json()["status"] in {"queued", "running", "done"}

    status = await wait_for_job(client, job_id)
    assert status["status"] == "done", status.get("error")
    assert status["error"] is None
    assert status["result"]["history"]
    assert 0.0 <= status["result"]["quality"] <= 1.0

    artifacts = status["artifacts"]
    assert "final.png" in artifacts
    assert "canvas.html" in artifacts
    assert "quality.json" in artifacts
    assert "iter_1.png" in artifacts

    png = await client.get(f"/generate/{job_id}/artifacts/final.png")
    assert png.status_code == 200
    assert png.headers["content-type"].startswith("image/png")
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"

    html = await client.get(f"/generate/{job_id}/artifacts/canvas.html")
    assert html.status_code == 200
    assert b"<canvas" in html.content

    quality = await client.get(f"/generate/{job_id}/artifacts/quality.json")
    assert quality.status_code == 200
    history = json.loads(quality.content)
    assert history[0]["iter"] == 1
    assert history[0]["questions"] > 0

    bad = await client.get(f"/generate/{job_id}/artifacts/not_allowed.txt")
    assert bad.status_code == 400

    missing = await client.get(f"/generate/{job_id}/artifacts/iter_99.png")
    assert missing.status_code == 404

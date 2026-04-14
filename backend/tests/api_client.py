from __future__ import annotations

import httpx

from app.main import app


async def request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        trust_env=False,
    ) as client:
        return await client.request(method, path, json=json)


"""Lightweight HTTP health endpoint for deployment platforms."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from .db import Database
from .state import StateStore


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: StateStore,
    database: Database,
) -> None:
    try:
        data = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError:
        writer.close()
        await writer.wait_closed()
        return

    request_line = data.decode(errors="ignore").split("\r\n", 1)[0]
    method, path, *_ = request_line.split(" ")
    if method.upper() != "GET" or path not in {"/", "/health", "/healthz"}:
        response = (
            "HTTP/1.1 404 Not Found\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return

    snapshot = await state.get_state()
    db_ok = database.is_connected if database else False
    payload = {
        "status": "ok",
        "dry_run": snapshot.dry_run,
        "persona": snapshot.persona.name,
        "database_connected": db_ok,
    }
    body = json.dumps(payload).encode()
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode() + body
    writer.write(response)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def start_health_server(
    host: str,
    port: int,
    state: StateStore,
    database: Database,
) -> asyncio.AbstractServer:
    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, state, database),
        host,
        port,
    )
    return server

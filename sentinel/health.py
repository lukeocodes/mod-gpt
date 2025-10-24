"""Lightweight HTTP health endpoint for deployment platforms."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from .db import Database
from .services.state import StateStore

# Avoid circular import by using TYPE_CHECKING
try:
    from .services.registration import RegistrationService
except ImportError:
    RegistrationService = None


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: StateStore,
    database: Database,
    registration_service: Optional["RegistrationService"] = None,
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
        response = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        writer.write(response.encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return

    snapshot = await state.get_state()
    db_ok = database.is_connected if database else False

    # Fetch active machines (last 5 minutes) via registration service
    active_machines = []
    machine_counts = {"active": 0, "total": 0}
    if registration_service:
        active = await registration_service.get_active_machines(max_age_minutes=5)
        machine_counts = await registration_service.get_machine_counts(max_age_minutes=5)
        active_machines = [
            {
                "machine_id": m["machine_id"],
                "hostname": m["hostname"],
                "version": m["bot_version"],
                "last_active": m["last_active"].isoformat() if m["last_active"] else None,
            }
            for m in active
        ]

    payload = {
        "status": "ok",
        "dry_run": snapshot.dry_run,
        "persona": snapshot.persona.name,
        "llm_configured": bool(snapshot.llm.api_key),
        "database_connected": db_ok,
        "machines": {
            "active": machine_counts["active"],
            "total": machine_counts["total"],
            "instances": active_machines,
        },
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
    registration_service: Optional["RegistrationService"] = None,
) -> asyncio.AbstractServer:
    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, state, database, registration_service),
        host,
        port,
    )
    return server

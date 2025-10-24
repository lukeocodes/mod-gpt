"""Machine registration and heartbeat service for multi-machine deployments."""

import asyncio
import logging
import socket
from typing import Optional

from sentinel.db import Database

logger = logging.getLogger(__name__)


class RegistrationService:
    """Manages machine registration and periodic heartbeats."""

    def __init__(
        self,
        database: Database,
        machine_id: Optional[str] = None,
        version: Optional[str] = None,
        heartbeat_interval: int = 300,  # 5 minutes in seconds
    ):
        """Initialize the registration service.

        Args:
            database: Database instance for registration
            machine_id: Unique machine identifier (uses hostname if None)
            version: Bot version string
            heartbeat_interval: Seconds between heartbeat updates (default: 300)
        """
        self._database = database
        self._machine_id = machine_id or socket.gethostname()
        self._version = version
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._hostname = socket.gethostname()

    @property
    def machine_id(self) -> str:
        """Get the machine ID."""
        return self._machine_id

    @property
    def is_running(self) -> bool:
        """Check if the heartbeat service is running."""
        return self._heartbeat_task is not None and not self._heartbeat_task.done()

    async def register(self) -> None:
        """Register or update this machine in the database."""
        if not self._database.is_connected:
            logger.warning("Cannot register machine - database not connected")
            return

        try:
            await self._database.register_machine(
                machine_id=self._machine_id,
                bot_version=self._version,
                hostname=self._hostname,
                metadata=None,
            )
            logger.info(
                "Machine registered: %s (hostname: %s, version: %s)",
                self._machine_id,
                self._hostname,
                self._version or "unknown",
            )
        except Exception:
            logger.exception("Failed to register machine")

    async def start_heartbeat(self) -> None:
        """Start the periodic heartbeat task.

        The heartbeat updates the machine's last_active timestamp
        at regular intervals to indicate the machine is still running.
        """
        if self._heartbeat_task is not None:
            logger.warning("Heartbeat task already running")
            return

        if not self._database.is_connected:
            logger.warning("Cannot start heartbeat - database not connected")
            return

        async def heartbeat_loop():
            """Internal heartbeat loop."""
            while True:
                try:
                    await asyncio.sleep(self._heartbeat_interval)
                    await self.register()  # Re-register to update last_active
                except asyncio.CancelledError:
                    logger.info("Heartbeat task cancelled")
                    break
                except Exception:
                    logger.exception("Failed to send machine heartbeat")

        self._heartbeat_task = asyncio.create_task(heartbeat_loop())
        logger.info(
            "Heartbeat started for machine %s (interval: %ds)",
            self._machine_id,
            self._heartbeat_interval,
        )

    async def stop_heartbeat(self) -> None:
        """Stop the periodic heartbeat task."""
        if self._heartbeat_task is None:
            return

        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        finally:
            self._heartbeat_task = None
            logger.info("Heartbeat stopped for machine %s", self._machine_id)

    async def get_active_machines(self, max_age_minutes: int = 5) -> list:
        """Get list of active machines.

        Args:
            max_age_minutes: Maximum age in minutes to consider a machine active

        Returns:
            List of active machine records
        """
        if not self._database.is_connected:
            return []

        try:
            return await self._database.fetch_active_machines(max_age_minutes=max_age_minutes)
        except Exception:
            logger.exception("Failed to fetch active machines")
            return []

    async def get_all_machines(self) -> list:
        """Get list of all registered machines.

        Returns:
            List of all machine records
        """
        if not self._database.is_connected:
            return []

        try:
            return await self._database.fetch_all_machines()
        except Exception:
            logger.exception("Failed to fetch all machines")
            return []

    async def get_machine_counts(self, max_age_minutes: int = 5) -> dict:
        """Get count of active and total machines.

        Args:
            max_age_minutes: Maximum age in minutes to consider a machine active

        Returns:
            Dictionary with 'active' and 'total' counts
        """
        if not self._database.is_connected:
            return {"active": 0, "total": 0}

        try:
            active = await self._database.fetch_active_machines(max_age_minutes=max_age_minutes)
            all_machines = await self._database.fetch_all_machines()
            return {
                "active": len(active),
                "total": len(all_machines),
            }
        except Exception:
            logger.exception("Failed to fetch machine counts")
            return {"active": 0, "total": 0}

    async def shutdown(self) -> None:
        """Clean shutdown of the registration service."""
        await self.stop_heartbeat()

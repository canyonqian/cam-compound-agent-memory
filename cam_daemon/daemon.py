"""
CAM Daemon Lifecycle Manager
============================

Handles daemon start/stop/restart/status operations.
Manages PID file, graceful shutdown, signal handling.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("cam_daemon.daemon")


class DaemonManager:
    """
    Manages the lifecycle of cam-daemon as a background process.

    Responsibilities:
    - PID file management (prevent multiple instances)
    - Graceful shutdown on SIGTERM/SIGINT
    - Status reporting
    - State persistence
    """

    def __init__(self, config):
        from .config import DaemonConfig

        self.config: DaemonConfig = config
        self._server = None
        self._engine = None
        self._scheduler = None
        self._running = False
        self._shutdown_event: Optional[asyncio.Event] = None

    @property
    def pid_path(self) -> Path:
        return Path(self.config.pid_file)

    @property
    def state_path(self) -> Path:
        return Path(self.config.state_file)

    def is_running(self) -> bool:
        """Check if a daemon instance is already running."""
        if not self.pid_path.exists():
            return False

        try:
            pid = int(self.pid_path.read_text().strip())
            # Check if process exists
            os.kill(pid, 0)
            return True
        except (ValueError, OSError):
            # Stale PID file
            self.pid_path.unlink(missing_ok=True)
            return False

    def get_status(self) -> dict:
        """Get current daemon status."""
        pid = None
        uptime_sec = 0
        state = "stopped"

        if self.is_running():
            state = "running"
            try:
                pid = int(self.pid_path.read_text().strip())
            except Exception:
                pass

            # Load state for more details
            if self.state_path.exists():
                try:
                    sdata = json.loads(self.state_path.read_text())
                    start_time = sdata.get("start_time", "")
                    if start_time:
                        from datetime import datetime

                        started = datetime.fromisoformat(start_time)
                        uptime_sec = (datetime.utcnow() - started).total_seconds()
                except Exception:
                    pass

        return {
            "state": state,
            "pid": pid,
            "port": self.config.port,
            "host": self.config.host,
            "wiki_path": self.config.wiki_path,
            "uptime_sec": round(uptime_sec),
            "version": "2.0.0",
        }

    async def start(self) -> None:
        """Start the daemon."""
        # Prevent double-start
        if self.is_running():
            existing_pid = int(self.pid_path.read_text().strip())
            raise RuntimeError(
                f"Daemon already running (PID {existing_pid}). Use 'cam daemon stop' first or 'cam daemon restart'."
            )

        logger.info("Starting CAM Daemon v2.0.0")
        logger.info(f"  Wiki: {self.config.wiki_path}")
        logger.info(f"  API : http://{self.config.host}:{self.config.port}")
        logger.info(f"  LLM : {self.config.llm.provider}/{self.config.llm.model}")

        # Ensure directories exist
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize engine
        from .server import CamEngine

        self._engine = CamEngine(self.config)

        # Write PID
        pid = os.getpid()
        self.pid_path.write_text(str(pid))

        # Write initial state
        from datetime import datetime

        state_data = {
            "start_time": datetime.utcnow().isoformat(),
            "pid": pid,
            "config": {
                "wiki_path": self.config.wiki_path,
                "port": self.config.port,
                "llm_provider": self.config.llm.provider,
                "llm_model": self.config.llm.model,
            },
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state_data, indent=2))

        # Start scheduler
        self._shutdown_event = asyncio.Event()
        await self._start_scheduler()

        # Create engine & register as global (needed by FastAPI handlers)
        from .server import create_server

        create_server(  # This sets the global _engine_instance
            engine=self._engine,
            host=self.config.host,
            port=self.config.port,
        )

        self._running = True
        logger.info(f"✅ Daemon started (PID {pid})")

    async def run_forever(self) -> None:
        """
        Run the daemon until shutdown signal.

        This is the main loop — call after start().
        """
        if not self._running:
            raise RuntimeError("Daemon not started. Call start() first.")

        # Register signal handlers for graceful shutdown
        if hasattr(asyncio, "add_signal_handler"):
            try:
                loop = asyncio.get_running_loop()

                def _signal_handler():
                    logger.info("Shutdown signal received, stopping...")
                    self._shutdown_event.set()

                for sig in (signal.SIGTERM, signal.SIGINT):
                    try:
                        loop.add_signal_handler(sig, _signal_handler)
                    except (OSError, ValueError):
                        pass
            except NotImplementedError:
                # Windows doesn't support add_signal_handler in some contexts
                pass

        # If we have FastAPI + uvicorn, run it
        from .server import HAS_FASTAPI, app as fastapi_app

        if HAS_FASTAPI:
            import uvicorn

            config = uvicorn.Config(
                app=fastapi_app,
                host=self.config.host,
                port=self.config.port,
                log_level="info",
            )
            server = uvicorn.Server(config)
            self._uvicorn_server = server

            # Run uvicorn but also monitor shutdown event
            # Note: asyncio.wait() requires Tasks, not coroutines!
            serve_task = asyncio.create_task(server.serve())
            shutdown_task = asyncio.create_task(self._shutdown_event.wait())

            done, pending = await asyncio.wait(
                [serve_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if self._shutdown_event.is_set():
                server.should_exit = True
                await serve_task
            else:
                # Server stopped on its own (unexpected)
                logger.warning("Uvicorn server stopped unexpectedly")
        else:
            # Fallback HTTP server
            from .server import _FallbackHandler

            _FallbackHandler.engine = self._engine
            from http.server import HTTPServer

            http_server = HTTPServer(
                (self.config.host, self.config.port),
                _FallbackHandler,
            )

            # Run with periodic shutdown check
            loop = asyncio.get_event_loop()
            loop.add_reader(http_server.fileno(), http_server.handle_request)

            try:
                await self._shutdown_event.wait()
            finally:
                loop.remove_reader(http_server.fileno())
                http_server.server_close()

        await self.stop()

    async def stop(self) -> None:
        """Gracefully stop the daemon."""
        logger.info("Stopping daemon...")

        self._running = False

        # Stop scheduler
        if self._scheduler:
            await self._scheduler.stop()

        # Clean up PID and state files
        if self.pid_path.exists():
            self.pid_path.unlink(missing_ok=True)

        logger.info("🛑 Daemon stopped")

    async def _start_scheduler(self) -> None:
        """Start background scheduled tasks."""
        from .scheduler import CamScheduler

        self._scheduler = CamScheduler(engine=self._engine, config=self.config)
        await self._scheduler.start()


# ── Signal imports (may not be available on Windows) ───────────
try:
    import signal
except ImportError:
    signal = None

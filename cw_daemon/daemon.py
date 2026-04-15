"""
CwDaemon Lifecycle Manager
==========================

Handles daemon start/stop/restart/status operations.
Manages PID file, graceful shutdown, signal handling.
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger("cw_daemon.daemon")


class DaemonManager:
    """
    Manages the lifecycle of cw-daemon as a background process.

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
                        uptime_sec = (
                            datetime.utcnow() - started
                        ).total_seconds()
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
                f"Daemon already running (PID {existing_pid}). "
                f"Use 'cw daemon stop' first or 'cw daemon restart'."
            )

        logger.info(f"Starting Compound Wiki Daemon v2.0.0")
        logger.info(f"  Wiki: {self.config.wiki_path}")
        logger.info(f"  API : http://{self.config.host}:{self.config.port}")
        logger.info(f"  LLM : {self.config.llm.provider}/{self.config.llm.model}")

        # Ensure directories exist
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize engine
        from .server import CwEngine
        self._engine = CwEngine(self.config)

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

        # Create server
        from .server import create_server
        self._server, _ = create_server(
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
        from .server import HAS_FASTAPI, app

        if HAS_FASTAPI:
            import uvicorn
            config = uvicorn.Config(
                app=app,
                host=self.config.host,
                port=self.config.port,
                log_level="info",
            )
            server = uvicorn.Server(config)

            # Run uvicorn but also monitor shutdown event
            async def _run_with_shutdown():
                task = asyncio.create_task(server.serve())

                # Wait for either shutdown or server completion
                done, pending = await asyncio.wait(
                    [task, self._shutdown_event.wait()],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if self._shutdown_event.is_set():
                    server.should_exit = True
                    await task

            await _run_with_shutdown()
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
        from .scheduler import CwScheduler
        self._scheduler = CwScheduler(engine=self._engine, config=self.config)
        await self._scheduler.start()


# ── Signal imports (may not be available on Windows) ───────────
try:
    import signal
except ImportError:
    signal = None

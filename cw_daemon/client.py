"""
CwDaemon Client — Lightweight SDK for Agent Integration
======================================================

Any Agent (Python/TypeScript/Shell/curl) can use this to talk to cw-daemon.

Usage (Python):
    from cw_daemon.client import CwClient

    client = CwClient("http://localhost:9877")
    result = await client.remember(user_msg, ai_response)

Usage (any language — HTTP):
    POST http://localhost:9877/hook
    {"user_message": "...", "ai_response": "...", "agent_id": "my-agent"}

    GET  http://localhost:9877/query?q=PostgreSQL
    GET  http://localhost:9877/stats
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("cw_daemon.client")


class CwClient:
    """
    Lightweight async/sync client for cw-daemon.

    This is what Agents use to interact with the daemon.
    Only ~80 lines of code.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:9877",
                 timeout_sec: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_sec
        # Lazy import of httpx/aiohttp
        self._session = None

    # ── Async API ─────────────────────────────────────────────

    async def remember(self, user_message: str, ai_response: str,
                      agent_id: str = "unknown",
                      session_id: str = "",
                      **metadata) -> Dict[str, Any]:
        """
        Send a conversation turn for automatic memory extraction.

        This is THE method that any Agent calls after each exchange.
        """
        return await self._post("/hook", {
            "user_message": user_message,
            "ai_response": ai_response,
            "agent_id": agent_id,
            "session_id": session_id,
            "metadata": metadata,
        })

    async def ingest(self, content: str,
                    source: str = "manual") -> Dict[str, Any]:
        """Manually ingest content into the knowledge base."""
        return await self._post("/ingest", {
            "content": content,
            "source": source,
        })

    async def query(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        """Query the Wiki knowledge base."""
        return await self._get("/query", {"q": question, "top_k": top_k})

    async def stats(self) -> Dict[str, Any]:
        """Get daemon and Wiki statistics."""
        return await self._get("/stats")

    async def health(self) -> Dict[str, Any]:
        """Check if daemon is running."""
        return await self._get("/health")

    # ── Sync API (for non-async contexts) ───────────────────────

    def remember_sync(self, user_message: str, ai_response: str,
                     agent_id: str = "unknown",
                     **kwargs) -> Dict[str, Any]:
        """Sync version of remember() for non-async contexts."""
        try:
            import urllib.request, json as _j
            payload = json.dumps({
                "user_message": user_message,
                "ai_response": ai_response,
                "agent_id": agent_id,
                **kwargs,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.base_url}/hook",
                data=payload,
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _j.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"Sync hook failed: {e}")
            return {
                "success": False,
                "status": "error",
                "message": str(e),
            }

    # ── Internal HTTP helpers ─────────────────────────────────

    async def _post(self, path: str, data: dict) -> dict:
        """Make an async POST request."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}{path}",
                    json=data,
                )
                resp.raise_for_status()
                return resp.json()

        except ImportError:
            # Fallback: use aiohttp or asyncio + urllib
            import aiohttp
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(
                    f"{self.base_url}{path}", json=data
                ) as resp:
                    return await resp.json()

        except Exception as e:
            logger.error(f"POST {path} failed: {e}")
            raise

    async def _get(self, path: str, params: dict = None) -> dict:
        """Make an async GET request."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}{path}", params=params or {}
                )
                resp.raise_for_status()
                return resp.json()
        except ImportError:
            import aiohttp
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.get(
                    f"{self.base_path}{path}", params=params or {}
                ) as resp:
                    return await resp.json()


# ── Convenience wrapper for one-liner integration ─────────────

class AutoRemember:
    """
    One-line integration for any Python-based AI Agent.

    Usage:
        auto = AutoRemember(agent_id="my-bot", daemon_url="http://localhost:9877")

        # In your conversation loop:
        reply = await my_llm.chat(user_msg)
        await auto(user_msg, reply)   # ← That's it!
    """

    def __init__(self, agent_id: str = "default",
                 daemon_url: str = "http://127.0.0.1:9877",
                 quiet: bool = True):
        self.client = CwClient(base_url=daemon_url)
        self.agent_id = agent_id
        self.quiet = quiet

    async def __call__(self, user_message: str, ai_response: str) -> dict:
        """Call this after every conversation turn."""
        result = await self.client.remember(
            user_message=user_message,
            ai_response=ai_response,
            agent_id=self.agent_id,
        )

        if not self.quiet and result.get("facts_written", 0) > 0:
            logger.info(
                f"🧠 Remembered {result['facts_written']} facts "
                f"from {self.agent_id}"
            )

        return result


# ── CLI helper: quick test connection ────────────────────────

def ping(daemon_url: str = "http://127.0.0.1:9877") -> bool:
    """Quick check if daemon is reachable. Returns True/False."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{daemon_url}/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("status") == "healthy"
    except Exception:
        return False

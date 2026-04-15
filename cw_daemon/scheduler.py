"""
CwScheduler — Background Task Scheduler
=======================================

Runs periodic maintenance tasks:
  - Daily LINT health check
  - Periodic index rebuild
  - Stats logging
  - Weekly summary generation
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("cw_daemon.scheduler")


class CwScheduler:
    """
    Lightweight scheduler for daemon background tasks.

    Uses asyncio tasks with sleep intervals (no cron dependency).
    All errors are caught internally to prevent task death.
    """

    def __init__(self, engine, config):
        self.engine = engine
        self.config = config

        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """Start all scheduled tasks."""
        if self._running:
            return

        self._running = True

        # Parse interval from cron-like config
        lint_interval = self._parse_interval(
            self.config.lint_schedule_cron,
            default_hours=24,
        )
        index_interval = self.config.index_rebuild_interval_min * 60
        stats_interval = self.config.stats_log_interval_min * 60

        self._tasks = [
            asyncio.create_task(self._task_loop(
                name="index-rebuild",
                func=self._rebuild_index,
                interval_sec=index_interval,
            )),
            asyncio.create_task(self._task_loop(
                name="stats-log",
                func=self._log_stats,
                interval_sec=stats_interval,
            )),
            asyncio.create_task(self._task_loop(
                name="daily-lint",
                func=self._run_lint,
                interval_sec=lint_interval,
            )),
        ]

        logger.info(f"Scheduler started: index={index_interval}s, "
                     f"stats={stats_interval}s, lint={lint_interval}s")

    async def stop(self) -> None:
        """Cancel all scheduled tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("Scheduler stopped")

    async def _task_loop(self, name: str, func, interval_sec: float) -> None:
        """
        Run a function at regular intervals.
        Catches all exceptions to keep the loop alive.
        """
        logger.debug(f"Scheduler '{name}' started (interval={interval_sec}s)")

        while self._running:
            try:
                await asyncio.sleep(interval_sec)
                if not self._running:
                    break

                start = time.time()
                await func()

                elapsed = time.time() - start
                logger.debug(f"[scheduler] {name} completed ({elapsed:.1f}s)")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[scheduler] Error in {name}: {e}", exc_info=True)
                # Wait a bit before retry on error
                await asyncio.sleep(60)

    async def _rebuild_index(self) -> None:
        """Rebuild wiki index file."""
        try:
            await self.engine._update_index()
            pages = await self.engine.wiki.list_pages()
            logger.info(f"[scheduler] Index rebuilt ({len(pages)} pages)")
        except Exception as e:
            logger.error(f"[scheduler] Index rebuild failed: {e}")

    async def _log_stats(self) -> None:
        """Log current stats for monitoring."""
        try:
            stats = await self.engine.get_stats()

            log_entry = (
                f"[{datetime.utcnow().isoformat()}] "
                f"hooks={stats['daemon']['hooks_received']} "
                f"processed={stats['daemon']['hooks_processed']} "
                f"throttled={stats['daemon']['hooks_throttled']} "
                f"facts={stats['daemon']['total_facts_written']} "
                f"errors={stats['daemon']['total_errors']} "
                f"pages={stats['wiki']['total_pages']}"
            )

            # Append to daemon log
            log_path = Path(self.config.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")

            logger.debug(log_entry)
        except Exception as e:
            logger.error(f"[scheduler] Stats log failed: {e}")

    async def _run_lint(self) -> None:
        """Run a health check / LINT audit on the Wiki."""
        try:
            pages = await self.engine.wiki.list_pages()
            issues = []

            total_facts = 0
            empty_pages = 0
            large_pages = 0

            for page in pages:
                content = await self.engine.wiki.read_page(page["path"])
                if not content or len(content.strip()) < 50:
                    empty_pages += 1
                    issues.append({
                        "severity": "warning",
                        "type": "empty_page",
                        "page": page["path"],
                        "message": f"Page is nearly empty ({len(content or '')} bytes)",
                    })

                # Count fact blocks
                fact_blocks = content.count("---") // 2 if content else 0
                total_facts += fact_blocks

                if page["size_bytes"] > 50000:
                    large_pages += 1
                    issues.append({
                        "severity": "info",
                        "type": "large_page",
                        "page": page["path"],
                        "message": f"Page is very large ({page['size_bytes']} bytes)",
                    })

            # Write LINT report
            report_path = Path(self.config.wiki_path) / ".lint-reports"
            report_path.mkdir(exist_ok=True)

            today = datetime.utcnow().strftime("%Y-%m-%d")
            report_file = report_path / f"lint-{today}.md"

            report_lines = [
                f"# Wiki LINT Report — {today}\n",
                f"\n## Summary\n",
                f"- **Total pages**: {len(pages)}",
                f"- **Total fact blocks**: ~{total_facts}",
                f"- **Empty/near-empty**: {empty_pages}",
                f"- **Large (>50KB)**: {large_pages}",
                f"- **Issues found**: {len(issues)}\n",
            ]

            if issues:
                report_lines.append("\n## Issues\n")
                for i, issue in enumerate(issues, 1):
                    emoji = {"error": "🔴", "warning": "⚠️", "info": "ℹ️"}
                    icon = emoji.get(issue.get("severity", ""), "•")
                    report_lines.append(
                        f"{i}. {icon} [{issue['page']}] {issue['message']}"
                    )
            else:
                report_lines.append("\n✅ No issues found. Wiki is healthy!\n")

            report_file.write_text("\n".join(report_lines), encoding="utf-8")

            logger.info(f"[scheduler] LINT complete: "
                         f"{len(pages)} pages, {len(issues)} issues")

        except Exception as e:
            logger.error(f"[scheduler] LINT failed: {e}", exc_info=True)

    @staticmethod
    def _parse_interval(cron_expr: str, default_hours: int = 24) -> float:
        """
        Very simple cron parser. Supports basic formats:
          - "0 8 * * *" → daily at 08:00
          - "*/30 * * * *" → every 30 minutes
          - integer string → seconds directly
        """
        try:
            seconds = float(cron_expr.strip())
            return max(seconds, 60)
        except ValueError:
            pass

        parts = cron_expr.split()

        if len(parts) >= 2 and parts[1].isdigit():
            hour = int(parts[1])
            # Daily schedule: convert hours to seconds
            return max(default_hours * 3600, 300)  # At least 5 min apart

        return default_hours * 3600


import time

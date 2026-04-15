#!/usr/bin/env python3
"""
CwDaemon Run Entry Point
=========================

This is the actual script that runs when `cw daemon start` is called.
It starts the HTTP server and blocks until shutdown.

Usage (internal):
    python cw_daemon/_run.py --config path/to/cw-daemon.json
    OR
    python -m cw_daemon._run --config path/to/cw-daemon.json
"""

import asyncio
import json
import logging
import os
import sys

# Add project root to path so imports work
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def setup_logging(log_path: str = ""):
    """Configure daemon logging."""
    log_format = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_path:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers,
    )


async def main(config_path: str):
    """Main entry point — load config, start engine, serve."""
    from .config import DaemonConfig
    from .daemon import DaemonManager
    
    # Load config
    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Parse LLM sub-config
    llm_data = data.pop("llm", {})
    config = DaemonConfig(**data)
    
    # Override LLM settings
    for k, v in llm_data.items():
        if hasattr(config.llm, k):
            setattr(config.llm, k, v)
    
    # Setup logging
    setup_logging(config.log_file)
    logger = logging.getLogger("cw_daemon")
    logger.info("=== Compound Wiki Daemon v2 Starting ===")
    logger.info(f"Config: {config_path}")
    
    # Create manager & start
    manager = DaemonManager(config)
    
    await manager.start()
    await manager.run_forever()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Compound Wiki Daemon")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    args = parser.parse_args()
    
    try:
        asyncio.run(main(args.config))
    except KeyboardInterrupt:
        print("\n🛑 Daemon interrupted.")

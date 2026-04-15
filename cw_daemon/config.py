"""
Daemon Configuration
====================

Centralized configuration for cw-daemon.
Supports file-based (JSON) and CLI overrides.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class LLMConfig:
    """LLM provider configuration for knowledge extraction."""
    provider: str = "openai"          # "openai" | "anthropic" | "ollama"
    model: str = "gpt-4o-mini"       # Extraction model (cheap is fine)
    api_key: str = ""
    base_url: str = ""                # Override API base URL (e.g., proxy)
    temperature: float = 0.1          # Low temp for consistent extraction
    max_tokens: int = 1024

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Create LLM config from environment variables."""
        return cls(
            provider=os.environ.get("CW_LLM_PROVIDER", "openai"),
            model=os.environ.get("CW_LLM_MODEL", "gpt-4o-mini"),
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", ""),
            base_url=os.environ.get("CW_LLM_BASE_URL", ""),
        )


@dataclass
class DaemonConfig:
    """Full daemon configuration."""
    wiki_path: str = "./wiki"
    raw_path: str = "./raw"
    port: int = 9877
    host: str = "127.0.0.1"

    # LLM
    llm: LLMConfig = field(default_factory=LLMConfig.from_env)

    # Throttling
    throttle_interval_sec: float = 10.0   # Minimum seconds between same-content hooks
    throttle_window_size: int = 50         # Hash history window

    # Deduplication
    dedup_similarity_threshold: float = 0.85

    # Scheduler
    lint_schedule_cron: str = "0 8 * * *"     # Daily at 08:00
    index_rebuild_interval_min: int = 60       # Rebuild index every hour
    stats_log_interval_min: int = 30           # Log stats every 30min

    # File paths
    pid_file: str = ""
    state_file: str = ""
    log_file: str = ""

    def __post_init__(self):
        if not self.pid_file:
            self.pid_file = str(
                Path(self.wiki_path).parent / ".daemon" / "cw-daemon.pid"
            )
        if not self.state_file:
            self.state_file = str(
                Path(self.wiki_path).parent / ".daemon" / "state.json"
            )
        if not self.log_file:
            self.log_file = str(
                Path(self.wiki_path).parent / ".daemon" / "daemon.log"
            )

    @classmethod
    def load(cls, path: Optional[str] = None, **overrides) -> "DaemonConfig":
        """Load config from JSON file + CLI overrides."""
        defaults = cls()

        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            llm_data = data.pop("llm", {})
            llm = LLMConfig(**{**defaults.llm.__dict__, **llm_data})
            cfg = cls(llm=llm, **{**defaults.__dict__, **data})
        else:
            cfg = defaults

        # Apply overrides (CLI args take precedence)
        for key, value in overrides.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
            elif hasattr(cfg.llm, key):
                setattr(cfg.llm, key, value)

        return cfg

    def save(self, path: Optional[str] = None) -> str:
        """Save current config to JSON file."""
        save_path = path or str(
            Path(self.wiki_path).parent / "cw-daemon.json"
        )

        data = {
            k: v for k, v in self.__dict__.items()
            if k not in ("llm",)
        }
        data["llm"] = self.llm.__dict__

        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        return save_path

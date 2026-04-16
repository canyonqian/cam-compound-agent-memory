"""
Base Plugin Interfaces
=======================

Abstract base classes for all data sources and output adapters.
Every plugin must implement BaseSource or extend from it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SourceType(Enum):
    """Supported source types."""

    API = "api"  # REST / GraphQL API endpoint
    BROWSER = "browser"  # Browser extension / bookmarklet
    CLIPBOARD = "clipboard"  # System clipboard monitor
    EMAIL = "email"  # IMAP email watcher
    RSS = "rss"  # RSS / Atom feed reader
    BOT = "bot"  # Telegram / Discord / WeChat bot
    FILE_WATCH = "file_watch"  # File system watcher
    CUSTOM = "custom"  # User-defined custom source
    WEBHOOK = "webhook"  # Incoming webhook (e.g. Zapier)


class ContentType(Enum):
    """Content type classification."""

    ARTICLE = "article"  # News article, blog post
    PAPER = "paper"  # Academic paper / research
    NOTE = "note"  # Personal note, thought
    BOOKMARK = "bookmark"  # URL bookmark (content not fetched yet)
    CODE = "code"  # Code snippet, gist
    IMAGE = "image"  # Image with text (OCR)
    PDF = "pdf"  # PDF document
    CONVERSATION = "conversation"  # Chat log, interview transcript
    TWEET = "tweet"  # Social media post
    VIDEO = "video"  # Video transcript
    UNKNOWN = "unknown"


@dataclass
class IngestItem:
    """
    A single item to be ingested into the knowledge base.

    This is the universal data format that all sources produce.
    The pipeline then processes each item into Wiki pages.

    Attributes:
        content: The raw content text (required)
        title: Human-readable title
        url: Original source URL (if any)
        source_type: Where this came from
        content_type: What kind of content this is
        metadata: Arbitrary extra data
        author: Content author (if known)
        tags: User-provided or auto-detected tags
        priority: 1=low, 2=normal, 3=high, 4=urgent
        created_at: When this item was created
    """

    content: str
    title: str = ""
    url: str = ""
    source_type: SourceType = SourceType.CUSTOM
    content_type: ContentType = ContentType.UNKNOWN
    metadata: Dict[str, Any] = field(default_factory=dict)
    author: str = ""
    tags: List[str] = field(default_factory=list)
    priority: int = 2  # normal
    created_at: datetime = field(default_factory=datetime.now)

    def to_raw_path(self, base_dir: Path) -> Path:
        """Generate a safe filename for storage in raw/."""
        safe_title = (
            self.title[:50]
            .replace("/", "-")
            .replace("\\", "-")
            .replace(":", "-")
            .replace("*", "-")
            .replace("?", "-")
            .replace('"', "")
            .replace("<", "")
            .replace(">", "")
            .replace("|", "-")
        )
        if not safe_title or safe_title.strip("-") == "":
            safe_title = f"untitled_{self.created_at.strftime('%Y%m%d_%H%M%S')}"

        timestamp = self.created_at.strftime("%Y%m%d_%H%M%S")
        ext = ".md"
        if self.content_type == ContentType.PDF:
            ext = ".txt"
        elif self.content_type == ContentType.CODE:
            ext = self.metadata.get("extension", ".md")

        return base_dir / f"{timestamp}_{safe_title}{ext}"


@dataclass
class IngestResult:
    """
    Result of processing an ingest item.

    Attributes:
        success: Whether processing succeeded
        item: The original item
        raw_path: Where it was saved in raw/
        wiki_pages_created: List of new/updated wiki page paths
        message: Human-readable status message
        error: Error details if failed
        processed_at: When processing completed
    """

    success: bool
    item: IngestItem
    raw_path: Optional[Path] = None
    wiki_pages_created: List[str] = field(default_factory=list)
    message: str = ""
    error: Optional[str] = None
    processed_at: datetime = field(default_factory=datetime.now)


@dataclass
class SourceConfig:
    """
    Configuration for a data source plugin.

    Attributes:
        enabled: Whether this source is active
        name: Display name
        source_type: Type identifier
        settings: Plugin-specific configuration
        auto_ingest: Automatically process items as they arrive
        batch_size: Number of items to batch before processing
        rate_limit: Max items per minute (0 = unlimited)
        filters: Content filtering rules
    """

    enabled: bool = True
    name: str = ""
    source_type: SourceType = SourceType.CUSTOM
    settings: Dict[str, Any] = field(default_factory=dict)
    auto_ingest: bool = True
    batch_size: int = 5
    rate_limit: int = 0  # 0 = no limit
    filters: Dict[str, Any] = field(default_factory=dict)


class BaseSource(ABC):
    """
    Abstract base class for all data sources.

    To create a custom source:
        class MySource(BaseSource):
            @property
            def source_type(self) -> SourceType:
                return SourceType.CUSTOM

            @property
            def display_name(self) -> str:
                return "My Custom Source"

            async def start(self):
                # Initialize connections, auth, etc.
                pass

            async def stop(self):
                # Clean up resources
                pass

            async def collect(self) -> List[IngestItem]:
                # Return new items to ingest
                return []

            async def health_check(self) -> Dict[str, Any]:
                return {"status": "ok"}

    Lifecycle:
        start() → [collect() loop] → stop()
    """

    def __init__(self, config: Optional[SourceConfig] = None):
        self.config = config or SourceConfig()
        self._running = False

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """Return the source type enum value."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for UI display."""
        ...

    @property
    def description(self) -> str:
        """Short description of what this source does."""
        return ""

    @property
    def running(self) -> bool:
        """Whether the source is currently active."""
        return self._running

    async def start(self) -> None:
        """
        Start the source.

        Called once before collect() loop begins.
        Use for initialization: open connections, authenticate, etc.
        """
        self._running = True

    async def stop(self) -> None:
        """
        Stop the source.

        Called when shutting down.
        Clean up all resources: close connections, release handles, etc.
        """
        self._running = False

    @abstractmethod
    async def collect(self) -> List[IngestItem]:
        """
        Collect new items from this source.

        Returns:
            List of new IngestItems ready for ingestion.
            Return empty list if nothing new.

        Note:
            This method will be called repeatedly in a loop.
            Implement your own polling/event logic inside.
            Rate limiting is handled by the framework.
        """
        ...

    async def health_check(self) -> Dict[str, Any]:
        """
        Check if the source is healthy and working.

        Returns:
            Dict with at least 'status' key ('ok', 'warning', 'error').
        """
        return {
            "status": "ok",
            "source": self.display_name,
            "type": self.source_type.value,
            "running": self._running,
        }

    def validate_item(self, item: IngestItem) -> bool:
        """
        Validate an item before accepting it.

        Override to add custom validation logic.
        Returns False to reject the item.
        """
        if not item.content or len(item.content.strip()) < 10:
            return False

        # Check filters from config
        filters = self.config.filters
        if filters.get("min_length", 0) > 0 and len(item.content) < filters["min_length"]:
            return False
        if filters.get("block_keywords"):
            content_lower = item.content.lower()
            for kw in filters["block_keywords"]:
                if kw.lower() in content_lower:
                    return False

        return True

    def __repr__(self):
        return f"<{self.__class__.__name__}(name={self.display_name!r}, running={self._running})>"


class BaseAdapter(ABC):
    """
    Abstract base class for output adapters.

    Adapters handle displaying/syncing Wiki content to external systems.
    Examples: Obsidian vault, Logseq graph, Web dashboard, etc.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Adapter identifier."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name."""
        ...

    async def on_wiki_update(self, action: str, page_path: str, content: Optional[str] = None):
        """
        Callback when Wiki content changes.

        Args:
            action: 'create' | 'update' | 'delete' | 'link'
            page_path: Relative path of the changed page
            content: New content (if available)
        """
        ...

    async def sync_all(self, wiki_dir: Path) -> Dict[str, Any]:
        """
        Perform a full sync of the Wiki to this adapter's target.

        Returns:
            Sync result summary.
        """
        return {"status": "ok", "adapter": self.adapter_name}

    async def health_check(self) -> Dict[str, Any]:
        """Check adapter health."""
        return {"status": "ok", "adapter": self.adapter_name}

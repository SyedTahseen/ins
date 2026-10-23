import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from utils import media as media_utils


@dataclass
class Tg:
    bot: Any
    chat_id: int
    max_bytes: int = 50 * 1_000_000
    proxy: str | None = None
    verify: bool | str = True

    async def _fetch(self, url: str) -> bytes:
        return await asyncio.to_thread(media_utils.download, url, self.max_bytes, self.proxy, self.verify)


@dataclass
class AppContext:
    cfg: Any
    ig: Any
    store: Any
    tg: Any = None
    modules: Any = None
    prefs: Any = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

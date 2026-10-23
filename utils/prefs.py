from copy import deepcopy
from typing import Any

from utils.logger import get_logger

log = get_logger("prefs")

PACES = ("safe", "normal", "fast")

DEFAULTS: dict[str, Any] = {
    "features": {},
    "pace": "normal",
    "dl_audio": True,
}


class Prefs:
    def __init__(self, store):
        self.store = store
        self.data: dict[str, Any] = deepcopy(DEFAULTS)

    async def load(self) -> None:
        try:
            saved = await self.store.get("prefs", {}) or {}
        except Exception:
            log.exception("Could not read preferences, using defaults")
            return
        for key, value in saved.items():
            if key in DEFAULTS:
                self.data[key] = value
        if not isinstance(self.data.get("features"), dict):
            self.data["features"] = {}

    async def _save(self) -> None:
        await self.store.set("prefs", self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    async def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.data[key] = value
        await self._save()

    def feature_on(self, name: str) -> bool:
        return bool(self.data["features"].get(name, True))

    async def set_feature(self, name: str, on: bool) -> None:
        self.data["features"][name] = bool(on)
        await self._save()

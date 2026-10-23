import zipfile
from pathlib import Path


class ZipParts:
    """Write files into one or more .zip archives, each kept under a size limit (Telegram caps uploads)."""

    OVERHEAD = 200  # rough per-entry zip header cost

    def __init__(self, folder: Path, stem: str, limit: int):
        self.folder = folder
        self.stem = stem
        self.limit = limit
        self.parts: list[Path] = []
        self.counts: list[int] = []
        self._zf: zipfile.ZipFile | None = None
        self._size = 0

    def _roll(self) -> None:
        self._close()
        path = self.folder / f"{self.stem}_part{len(self.parts) + 1}.zip"
        # Photos and videos are already compressed, so just store them.
        self._zf = zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True)
        self.parts.append(path)
        self.counts.append(0)
        self._size = 0

    def _close(self) -> None:
        if self._zf is not None:
            self._zf.close()
            self._zf = None

    def add(self, name: str, data: bytes, force: bool = False, counted: bool = True) -> None:
        cost = len(data) + self.OVERHEAD + len(name) * 2
        if self._zf is None or (not force and self._size > 0 and self._size + cost > self.limit):
            self._roll()
        self._zf.writestr(name, data)
        self._size += cost
        if counted:
            self.counts[-1] += 1

    def finish(self) -> list[Path]:
        self._close()
        if len(self.parts) == 1:
            single = self.folder / f"{self.stem}.zip"
            self.parts[0].rename(single)
            self.parts[0] = single
        return self.parts

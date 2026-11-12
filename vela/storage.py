"""Disk accounting for downloads and temporary swath files."""

from __future__ import annotations

from pathlib import Path


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


class StorageMeter:
    def __init__(self, root: Path):
        self.root = root
        self.downloaded = 0
        self.peak = directory_bytes(root)
        self.notes: list[str] = []

    def add_download(self, nbytes: int) -> None:
        self.downloaded += int(nbytes)
        self.sample()

    def sample(self) -> int:
        current = directory_bytes(self.root)
        if current > self.peak:
            self.peak = current
        return current

    def report(self) -> dict:
        current = self.sample()
        return {
            "bytes_downloaded": self.downloaded,
            "peak_temporary_bytes": self.peak,
            "current_bytes": current,
        }

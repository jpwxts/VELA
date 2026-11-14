"""Guardrails for raw granule downloads.

New downloads default to Iloilo, Philippines. Overseas bulk fetches stay off
while downloads_enabled is false. Cached files are reused when present.
"""

from __future__ import annotations

from pathlib import Path

from vela.settings import DATA_DIR, region_by_id, settings


def downloads_enabled() -> bool:
    cfg = settings()
    return bool(cfg.get("downloads_enabled", False))


def default_download_region() -> dict:
    cfg = settings()
    region_id = cfg.get("default_download_region_id") or (cfg.get("download_policy") or {}).get(
        "default_region_id", "iloilo"
    )
    return region_by_id(region_id)


def assert_downloads_allowed(authorize: bool = False) -> None:
    """Raise when a download would start during cleanup or without authorization."""

    if not authorize:
        raise RuntimeError(
            "Download blocked: pass --i-authorize-download after reviewing the size estimate. "
            "No bulk download was started."
        )
    if not downloads_enabled():
        raise RuntimeError(
            "Download blocked: config/settings.json has downloads_enabled=false "
            "(Philippines-first cleanup mode). Set downloads_enabled=true only when you intend "
            "to fetch new Iloilo (or explicitly selected) granules."
        )


def missing_names(names: list[str], destination: Path) -> list[str]:
    """Return catalog names not already present under destination (cache reuse)."""

    present = {path.name for path in destination.rglob("*") if path.is_file()} if destination.exists() else set()
    # Also accept the same basename anywhere under data/raw to avoid re-fetching known granules.
    raw_root = DATA_DIR / "raw"
    if raw_root.exists():
        present.update(path.name for path in raw_root.rglob("*") if path.is_file())
    return [name for name in names if name not in present]


def estimate_message(region: dict, start: str, end: str, report: dict, missing: list[str]) -> str:
    estimated = int(report.get("estimated_transfer_bytes") or 0)
    cached = int(report.get("unique_files") or 0) - len(missing)
    return (
        f"{region['name']} ({region['id']}) {start} → {end}: "
        f"{report.get('unique_files', 0)} catalog files, "
        f"{len(missing)} missing locally, ~{cached} reusable from cache, "
        f"about {estimated / 1e9:.3f} GB estimated transfer "
        f"({report.get('unknown_size_count', 0)} sizes unknown). "
        f"Bbox {region['west']},{region['south']},{region['east']},{region['north']}."
    )

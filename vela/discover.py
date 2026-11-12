"""Metadata discovery through earthaccess, before any file is downloaded."""

from __future__ import annotations

from vela.pipeline import build_catalog, describe_granule, search_product, try_login
from vela.settings import settings


def discover_week(region: dict, start: str, end: str, config: dict | None = None) -> tuple[dict, dict]:
    cfg = config or settings()
    bbox = (region["west"], region["south"], region["east"], region["north"])
    login = try_login()
    hits = {}
    objects = {}
    versions = {}
    errors = {}
    for product_id, product in cfg["products"].items():
        results, version, error = search_product(
            product["short_name"],
            product["version"],
            bbox,
            start,
            end,
        )
        versions[product_id] = version
        errors[product_id] = error
        described = []
        for granule in results or []:
            info = describe_granule(granule)
            info["product"] = product_id
            described.append(info)
            if info.get("name"):
                objects[info["name"]] = granule
        hits[product_id] = described
    report = build_catalog(hits, bbox, cfg)
    for product_id in cfg["products"]:
        report["files_per_product"].setdefault(product_id, 0)
    report.update(
        {
            "discovery_client": "earthaccess",
            "earthdata_login": bool(login),
            "region_id": region["id"],
            "region_name": region["name"],
            "start": start,
            "end": end,
            "bbox": list(bbox),
            "versions": versions,
            "search_errors": errors,
        }
    )
    return report, objects

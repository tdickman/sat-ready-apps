from __future__ import annotations

import json
import logging
import base64
import os
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from xml.sax.saxutils import escape

from downloader import PACKAGE_NAME_RE, download, get_app_info, load_config
from parser import parse_apk

logger = logging.getLogger(__name__)

CACHE_DAYS_DEFAULT = 30


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _load_seed_list(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Seed list must be a JSON array")
    seen = set()
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError(f"Seed entry must be an object: {entry}")
        pkg = entry.get("package_name", "")
        if not isinstance(pkg, str) or not PACKAGE_NAME_RE.fullmatch(pkg):
            raise ValueError(f"Seed entry missing package_name: {entry}")
        if pkg in seen:
            raise ValueError(f"Duplicate package in seed list: {pkg}")
        seen.add(pkg)
    return data


def _load_previous_catalog(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        entries = data.get("apps", data) if isinstance(data, dict) else data
        if isinstance(entries, list):
            return {
                e["package_name"]: e
                for e in entries
                if isinstance(e, dict) and "package_name" in e
            }
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load previous catalog %s: %s", path, e)
        return {}


def _is_cache_fresh(apk_path: Path, cache_days: int) -> bool:
    if not apk_path.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - apk_path.stat().st_mtime
    return age < cache_days * 86400


def _resolve_icon_url(
    package_name: str,
    apk_path: Optional[Path],
    parser_result: dict,
    config: dict,
) -> Optional[str]:
    info = get_app_info(package_name, config)
    if info and info.get("icon_url"):
        return info["icon_url"]
    icon_path = parser_result.get("icon_path")
    if icon_path and apk_path:
        icon_url = _extract_icon_data_url(apk_path, icon_path)
        if icon_url:
            return icon_url
    return _letter_icon_data_url(parser_result.get("app_name") or package_name)


def _extract_icon_data_url(apk_path: Path, icon_path: str) -> Optional[str]:
    if Path(icon_path).is_absolute() or ".." in Path(icon_path).parts:
        return None
    try:
        with zipfile.ZipFile(apk_path) as archive:
            data = archive.read(icon_path)
        if not data or len(data) > 1024 * 1024:
            return None
    except (OSError, KeyError, zipfile.BadZipFile):
        return None

    suffix = Path(icon_path).suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix)
    if not mime:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _letter_icon_data_url(app_name: str) -> str:
    initial = (app_name.strip()[:1] or "?").upper()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
        '<rect width="96" height="96" rx="18" fill="#334155"/>'
        f'<text x="48" y="63" text-anchor="middle" font-family="sans-serif" '
        f'font-size="48" fill="white">{escape(initial)}</text></svg>'
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _build_store_urls(package_name: str, config: dict) -> dict:
    play_url = config.get("play_store_url_template", "")
    fdroid_url = config.get("fdroid_url_template", "")
    return {
        "play_store_url": play_url.format(package_name=package_name) if play_url else None,
        "fdroid_url": fdroid_url.format(package_name=package_name) if fdroid_url else None,
    }


def process_package(
    package_name: str,
    category: str,
    config: dict,
) -> dict:
    cache_dir = Path(config.get("apk_cache_dir", "apk_cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_days = config.get("crawler", {}).get("cache_days", CACHE_DAYS_DEFAULT)

    apk_path = _find_cached_apk(cache_dir, package_name)
    downloaded = False
    cached = bool(apk_path)

    if apk_path and _is_cache_fresh(apk_path, cache_days):
        logger.debug("Using cached APK for %s", package_name)
    else:
        apk_path = download(package_name, output_dir=cache_dir, config=config)
        downloaded = True

    if not apk_path:
        return {
            "package_name": package_name,
            "error": "download_failed",
            "downloaded": False,
            "status": "error",
            "cached": cached,
        }

    parser_result = parse_apk(apk_path)

    if parser_result.get("error") and not downloaded:
        logger.warning("Cached APK for %s could not be parsed; retrying download", package_name)
        try:
            apk_path.unlink()
        except OSError:
            pass
        apk_path = download(package_name, output_dir=cache_dir, config=config)
        downloaded = True
        if apk_path:
            parser_result = parse_apk(apk_path)

    if parser_result.get("error"):
        return {
            "package_name": package_name,
            "error": "parse_failed",
            "downloaded": downloaded,
            "status": "error",
            "cached": cached,
        }

    parsed_package = parser_result.get("package_name")
    if parsed_package not in (None, package_name):
        return {
            "package_name": package_name,
            "error": "package_mismatch",
            "downloaded": downloaded,
            "status": "error",
            "cached": cached,
        }

    if not parser_result.get("satellite_optimized", False):
        return {
            "package_name": package_name,
            "error": None,
            "satellite_optimized": False,
            "downloaded": downloaded,
            "status": "negative",
            "cached": cached,
        }

    app_name = parser_result.get("app_name") or package_name
    icon_url = _resolve_icon_url(package_name, apk_path, parser_result, config)
    store_urls = _build_store_urls(package_name, config)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "package_name": package_name,
        "app_name": app_name,
        "icon_url": icon_url,
        "category": category,
        "last_verified": now,
        "downloaded": downloaded,
        "error": None,
        "satellite_optimized": True,
        "status": "positive",
        "cached": cached,
        **store_urls,
    }


def _find_cached_apk(cache_dir: Path, package_name: str) -> Optional[Path]:
    if not cache_dir.exists():
        return None
    candidates = [
        f
        for f in cache_dir.iterdir()
        if f.is_file()
        and f.suffix.lower() in {".apk", ".xapk", ".apks"}
        and (f.stem == package_name or f.stem.startswith(f"{package_name}-"))
    ]
    return max(candidates, key=lambda f: f.stat().st_mtime, default=None)


def _write_catalog(
    output_path: Path,
    apps: list[dict],
    previous: dict[str, dict],
    summary: dict,
    failed_packages: set[str],
) -> None:
    current_apps = {app["package_name"]: app for app in apps if app.get("satellite_optimized")}
    for package_name in failed_packages:
        if package_name not in current_apps and package_name in previous:
            current_apps[package_name] = previous[package_name]

    apps = list(current_apps.values())
    previous_pkgs = set(previous.keys())
    current_pkgs = {a["package_name"] for a in apps}

    new_packages = current_pkgs - previous_pkgs
    for app in apps:
        app["new_addition"] = app["package_name"] in new_packages

    seen = set()
    deduped = []
    for app in apps:
        pkg = app["package_name"]
        if pkg in seen:
            logger.warning("Duplicate package in output, skipping: %s", pkg)
            continue
        seen.add(pkg)
        deduped.append(app)

    catalog = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_apps": len(deduped),
            "new_additions": len(new_packages),
            "new_packages": sorted(new_packages),
            "summary": summary,
        },
        "apps": deduped,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as tmp:
            json.dump(catalog, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
            temporary_path = Path(tmp.name)
        os.replace(temporary_path, output_path)
    except OSError:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise
    logger.info("Catalog written to %s (%d apps, %d new)", output_path, len(deduped), len(new_packages))


def run_crawl(config: dict) -> dict:
    seed_path = config.get("seed_list_path", "seed_list.json")
    output_path = Path(config.get("output_path", "catalog.json"))
    max_workers = config.get("crawler", {}).get("max_workers", 5)
    seed_list = _load_seed_list(seed_path)

    logger.info("Starting crawl: %d apps, %d workers", len(seed_list), max_workers)

    previous = _load_previous_catalog(output_path)

    results: list[dict] = []
    errors = 0
    downloaded = 0
    sat_found = 0
    cached_skipped = 0
    failed_packages: set[str] = set()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                process_package,
                entry["package_name"],
                entry.get("category", ""),
                config,
            ): entry["package_name"]
            for entry in seed_list
        }

        for future in as_completed(future_map):
            pkg = future_map[future]
            try:
                result = future.result()
                if result.get("error"):
                    errors += 1
                    failed_packages.add(pkg)
                    log = logger.debug if config.get("quiet", False) else logger.warning
                    log("Failed %s: %s", pkg, result["error"])
                results.append(result)
                if result.get("downloaded"):
                    downloaded += 1
                if result.get("cached") and not result.get("downloaded"):
                    cached_skipped += 1
                if result.get("satellite_optimized"):
                    sat_found += 1
            except Exception as e:
                errors += 1
                failed_packages.add(pkg)
                logger.error("Unhandled exception for %s: %s", pkg, e)

    summary = {
        "total_processed": len(seed_list),
        "downloaded": downloaded,
        "satellite_optimized_found": sat_found,
        "errors": errors,
        "cached_skipped": cached_skipped,
    }

    logger.info(
        "Crawl complete: %d processed, %d downloaded, %d sat-optimized, %d errors",
        summary["total_processed"],
        summary["downloaded"],
        summary["satellite_optimized_found"],
        summary["errors"],
    )

    _write_catalog(output_path, results, previous, summary, failed_packages)

    return summary


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("config.yaml")
    try:
        config = load_config(config_path)
        config_dir = config_path.resolve().parent
        for key in ("seed_list_path", "output_path", "apk_cache_dir"):
            value = Path(config.get(key, ""))
            if value and not value.is_absolute():
                config[key] = str(config_dir / value)
    except Exception as e:
        logger.error("Failed to load config %s: %s", config_path, e)
        sys.exit(1)

    _setup_logging(config.get("log_level", "INFO"))

    summary = run_crawl(config)

    if summary.get("errors", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

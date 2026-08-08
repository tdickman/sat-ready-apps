from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from xml.sax.saxutils import escape

import requests
from justapk.sources.apkpure import APKPureSource

from downloader import PACKAGE_NAME_RE, download_with_diagnostics, load_config
from parser import (
    AAPT2_TIMEOUT_SECONDS,
    _aapt_attribute,
    _run_aapt2_dump,
    configure_parser_logging,
    parse_apk,
)

logger = logging.getLogger(__name__)

CACHE_DAYS_DEFAULT = 30
SCAN_DAYS_DEFAULT = 30


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


def _load_previous_scan_state(path: Path, previous_apps: dict[str, dict]) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load scan state %s: %s", path, e)
        return {}

    raw_state = data.get("scanned", {}) if isinstance(data, dict) else {}
    if isinstance(raw_state, list):
        state = {
            entry["package_name"]: entry
            for entry in raw_state
            if isinstance(entry, dict) and entry.get("package_name")
        }
    elif isinstance(raw_state, dict):
        state = {
            package_name: entry
            for package_name, entry in raw_state.items()
            if isinstance(entry, dict)
        }
    else:
        state = {}

    # Catalogs created before scan-state tracking can still avoid rescanning positives.
    for package_name, app in previous_apps.items():
        if package_name in state:
            if not state[package_name].get("first_verified_at") and app.get("first_verified_at"):
                state[package_name]["first_verified_at"] = app["first_verified_at"]
            continue
        state[package_name] = {
            "package_name": package_name,
            "category": app.get("category", ""),
            "satellite_optimized": True,
            "status": "positive",
            "last_scanned": app.get("last_verified"),
            "first_verified_at": app.get("first_verified_at"),
        }
    return state


def _is_scan_fresh(scan: Optional[dict], scan_days: int) -> bool:
    if not scan or scan.get("status") not in {"positive", "negative"}:
        return False
    last_scanned = scan.get("last_scanned")
    if not last_scanned:
        return False
    try:
        timestamp = datetime.fromisoformat(last_scanned.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            timestamp = datetime.strptime(last_scanned, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return False
    return (datetime.now(timezone.utc) - timestamp).total_seconds() < scan_days * 86400


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
    icon_url = _store_icon_url(package_name, config)
    if icon_url:
        return icon_url
    icon_path = parser_result.get("icon_path")
    if icon_path and apk_path:
        timeout = config.get("crawler", {}).get("aapt2_timeout", AAPT2_TIMEOUT_SECONDS)
        icon_url = _extract_icon_data_url(apk_path, icon_path, timeout)
        if icon_url:
            return icon_url
    return _letter_icon_data_url(parser_result.get("app_name") or package_name)


def _store_icon_url(package_name: str, config: dict) -> Optional[str]:
    """Resolve the app icon URL from the APKPure detail API."""
    source = APKPureSource()
    proxy = config.get("proxy", {})
    if proxy.get("enabled", False):
        proxy_url = (
            f"{proxy.get('scheme', 'socks5')}://{proxy.get('host', '127.0.0.1')}"
            f":{proxy.get('port', 1080)}"
        )
        source.session.trust_env = False
        source.session.proxies = {"http": proxy_url, "https": proxy_url}
    try:
        detail = source._get_detail(package_name)
    except Exception as e:
        logger.debug("Icon lookup failed for %s: %s", package_name, e)
        return None
    if not detail:
        return None
    icon = detail.get("icon") or {}
    for key in ("original", "thumbnail"):
        candidate = (icon.get(key) or {}).get("url")
        if isinstance(candidate, str) and candidate:
            return _larger_icon_url(candidate)
    return None


def _larger_icon_url(url: str, size: int = 256) -> str:
    """Request a higher-resolution rendering when the store CDN supports a size query."""
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if "w" in query:
        query["w"] = [str(size)]
        parsed = parsed._replace(query=urlencode(query, doseq=True))
    return urlunsplit(parsed)


def _extract_icon_data_url(apk_path: Path, icon_path: str, timeout: float) -> Optional[str]:
    if Path(icon_path).is_absolute() or ".." in Path(icon_path).parts:
        return None
    suffix = Path(icon_path).suffix.lower()
    if suffix == ".xml":
        return _extract_adaptive_icon_data_url(apk_path, icon_path, timeout)

    try:
        with zipfile.ZipFile(apk_path) as archive:
            info = archive.getinfo(icon_path)
            if info.file_size > 1024 * 1024:
                return None
            data = archive.read(icon_path)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None

    return _raster_data_url(suffix, data)


_ADAPTIVE_SLOT_PRIORITY = ["foreground", "background", "monochrome"]
_DENSITY_RANK = {
    "xxxhdpi": 6,
    "xxhdpi": 5,
    "xhdpi": 4,
    "hdpi": 3,
    "tvdpi": 2,
    "mdpi": 1,
}


def _extract_adaptive_icon_data_url(
    apk_path: Path, icon_path: str, timeout: float
) -> Optional[str]:
    try:
        xmltree = _run_aapt2_dump(["xmltree", "--file", icon_path], apk_path, timeout)
        resources = _run_aapt2_dump(["resources"], apk_path, timeout)
    except (RuntimeError, TimeoutError):
        return None

    refs = _parse_adaptive_icon_refs(xmltree)
    file_map = _load_resource_files(resources)
    for slot in _ADAPTIVE_SLOT_PRIORITY:
        ref = refs.get(slot)
        if not ref:
            continue
        entries = file_map.get(ref.lstrip("@"), [])
        raster = [entry for entry in entries if entry[2] in {"PNG", "JPEG", "WEBP"}]
        if not raster:
            continue
        raster.sort(key=lambda entry: _DENSITY_RANK.get(entry[0], 0), reverse=True)
        resource_path = raster[0][1]
        try:
            with zipfile.ZipFile(apk_path) as archive:
                info = archive.getinfo(resource_path)
                if info.file_size > 1024 * 1024:
                    continue
                data = archive.read(resource_path)
        except (OSError, KeyError, zipfile.BadZipFile):
            continue
        url = _raster_data_url(Path(resource_path).suffix.lower(), data)
        if url:
            return url
    return None


def _parse_adaptive_icon_refs(xmltree_output: str) -> dict[str, Optional[str]]:
    refs: dict[str, Optional[str]] = {}
    current_slot: Optional[str] = None
    adaptive_indent: Optional[int] = None
    for line in xmltree_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("E: adaptive-icon"):
            adaptive_indent = len(line) - len(line.lstrip())
            current_slot = None
            continue
        if adaptive_indent is None:
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= adaptive_indent:
            adaptive_indent = None
            current_slot = None
            continue
        if stripped.startswith(("E: background", "E: foreground", "E: monochrome")):
            current_slot = stripped.split()[1].split("(")[0]
            continue
        if current_slot and stripped.startswith("A: "):
            name, value = _aapt_attribute(line)
            if name == "drawable" and value and value.startswith("@"):
                refs[current_slot] = value
    return refs


_RESOURCE_ID_RE = re.compile(r"^    resource (0x[0-9a-f]+) ")
_RESOURCE_FILE_RE = re.compile(r"^      \(([^)]*)\) \(file\) (\S+) type=(\S+)$")


def _load_resource_files(
    resources_output: str,
) -> dict[str, list[tuple[str, str, str]]]:
    files: dict[str, list[tuple[str, str, str]]] = {}
    current_id: Optional[str] = None
    for line in resources_output.splitlines():
        if line.startswith("    resource "):
            match = _RESOURCE_ID_RE.match(line)
            current_id = match.group(1) if match else None
            if current_id:
                files.setdefault(current_id, [])
            continue
        if current_id:
            match = _RESOURCE_FILE_RE.match(line)
            if match:
                files[current_id].append((match.group(1), match.group(2), match.group(3)))
    return files


def _raster_data_url(suffix: str, data: bytes) -> Optional[str]:
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix)
    if not mime or not data:
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


def _store_url_status(url: str, config: dict) -> tuple[Optional[int], Optional[str]]:
    session = requests.Session()
    session.trust_env = False
    proxy = config.get("proxy", {})
    if proxy.get("enabled", False):
        proxy_url = (
            f"{proxy.get('scheme', 'socks5h')}://{proxy.get('host', '127.0.0.1')}"
            f":{proxy.get('port', 1080)}"
        )
        session.proxies = {"http": proxy_url, "https": proxy_url}
    try:
        response = session.get(
            url,
            allow_redirects=True,
            stream=True,
            timeout=config.get("crawler", {}).get("per_source_timeout", 30),
        )
        status = response.status_code
        response.close()
        return status, None
    except requests.RequestException as e:
        logger.debug("Store link unavailable %s: %s", url, e)
        return None, str(e)
    finally:
        session.close()


def _store_url_is_available(url: str, config: dict) -> bool:
    status, _ = _store_url_status(url, config)
    return status is not None and status < 400


def _validate_seed_package(package_name: str, config: dict) -> dict:
    template = config.get("play_store_url_template", "")
    if not template:
        return {
            "package_name": package_name,
            "status": "unavailable",
            "detail": "play_store_url_template is not configured",
        }

    url = template.format(package_name=package_name)
    status, error_detail = _store_url_status(url, config)
    if status == 200:
        return {
            "package_name": package_name,
            "status": "valid",
            "http_status": status,
            "url": url,
        }
    if status == 404:
        return {
            "package_name": package_name,
            "status": "rejected",
            "detail": "Google Play returned HTTP 404",
            "http_status": status,
            "url": url,
        }

    detail = f"Google Play returned HTTP {status}" if status is not None else error_detail
    return {
        "package_name": package_name,
        "status": "unavailable",
        "detail": detail or "Google Play validation failed",
        "http_status": status,
        "url": url,
    }


def _validate_seed_entries(
    entries: list[dict], config: dict, max_workers: int
) -> tuple[list[dict], dict[str, dict], list[dict]]:
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_validate_seed_package, entry["package_name"], config): entry
            for entry in entries
        }
        for future in as_completed(future_map):
            entry = future_map[future]
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "package_name": entry["package_name"],
                    "status": "unavailable",
                    "detail": str(e),
                }
            results.append({**result, "category": entry.get("category", "")})

    results.sort(key=lambda result: result["package_name"])
    rejected = {
        result["package_name"]: result
        for result in results
        if result["status"] == "rejected"
    }
    accepted_packages = {
        result["package_name"]
        for result in results
        if result["status"] != "rejected"
    }
    accepted = [entry for entry in entries if entry["package_name"] in accepted_packages]
    return accepted, rejected, results


def _build_store_urls(package_name: str, config: dict) -> dict:
    play_url = config.get("play_store_url_template", "")
    fdroid_url = config.get("fdroid_url_template", "")
    validate = config.get("validate_store_links", True)

    def resolve(template: str) -> Optional[str]:
        if not template:
            return None
        url = template.format(package_name=package_name)
        if (
            template == play_url
            and package_name in config.get("_validated_play_packages", set())
        ):
            return url
        return url if not validate or _store_url_is_available(url, config) else None

    return {
        "play_store_url": resolve(play_url),
        "fdroid_url": resolve(fdroid_url),
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
    download_error = None

    if apk_path and _is_cache_fresh(apk_path, cache_days):
        logger.debug("Using cached APK for %s", package_name)
    else:
        apk_path, download_error = download_with_diagnostics(
            package_name, output_dir=cache_dir, config=config
        )
        downloaded = True

    if not apk_path:
        return {
            "package_name": package_name,
            "category": category,
            "error": "download_failed",
            "error_detail": download_error,
            "downloaded": False,
            "status": "error",
            "cached": cached,
        }

    parser_result = parse_apk(
        apk_path,
        timeout=config.get("crawler", {}).get("aapt2_timeout", 60),
    )

    if parser_result.get("error") and not downloaded:
        logger.warning("Cached APK for %s could not be parsed; retrying download", package_name)
        try:
            apk_path.unlink()
        except OSError:
            pass
        apk_path, download_error = download_with_diagnostics(
            package_name, output_dir=cache_dir, config=config
        )
        downloaded = True
        if not apk_path:
            return {
                "package_name": package_name,
                "category": category,
                "error": "download_failed",
                "error_detail": download_error,
                "downloaded": False,
                "status": "error",
                "cached": cached,
            }
        parser_result = parse_apk(
            apk_path,
            timeout=config.get("crawler", {}).get("aapt2_timeout", 60),
        )

    if parser_result.get("error"):
        return {
            "package_name": package_name,
            "category": category,
            "error": "parse_failed",
            "error_detail": parser_result.get("error"),
            "downloaded": downloaded,
            "status": "error",
            "cached": cached,
        }

    parsed_package = parser_result.get("package_name")
    if parsed_package not in (None, package_name):
        return {
            "package_name": package_name,
            "category": category,
            "error": "package_mismatch",
            "error_detail": f"downloaded package {parsed_package!r}",
            "downloaded": downloaded,
            "status": "error",
            "cached": cached,
        }

    if not parser_result.get("satellite_optimized", False):
        return {
            "package_name": package_name,
            "category": category,
            "error": None,
            "satellite_optimized": False,
            "downloaded": downloaded,
            "status": "negative",
            "cached": cached,
            "last_scanned": datetime.now(timezone.utc).isoformat(),
        }

    app_name = parser_result.get("app_name") or package_name
    icon_url = _resolve_icon_url(package_name, apk_path, parser_result, config)
    store_urls = _build_store_urls(package_name, config)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scanned_at = datetime.now(timezone.utc).isoformat()

    return {
        "package_name": package_name,
        "app_name": app_name,
        "icon_url": icon_url,
        "category": category,
        "last_verified": now,
        "last_scanned": scanned_at,
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
    results: list[dict],
    previous: dict[str, dict],
    previous_scans: dict[str, dict],
    summary: dict,
    failed_packages: set[str],
    current_packages: set[str],
) -> None:
    current_apps = {
        result["package_name"]: result
        for result in results
        if result.get("status") == "positive"
    }
    for result in results:
        if result.get("status") == "skipped" and result.get("satellite_optimized"):
            package_name = result["package_name"]
            if package_name in previous:
                current_apps[package_name] = previous[package_name]
    for package_name in failed_packages:
        if package_name not in current_apps and package_name in previous:
            current_apps[package_name] = previous[package_name]

    apps = list(current_apps.values())
    previous_pkgs = set(previous.keys())
    current_pkgs = {a["package_name"] for a in apps}

    new_packages = current_pkgs - previous_pkgs
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for app in apps:
        package_name = app["package_name"]
        previous_app = previous.get(package_name, {})
        previous_scan = previous_scans.get(package_name, {})
        previous_positive_scan = previous_scan if previous_scan.get("status") == "positive" else {}
        first_verified_at = previous_app.get("first_verified_at") or previous_scan.get("first_verified_at")
        if not isinstance(first_verified_at, str) or not first_verified_at.strip():
            first_verified_at = (
                previous_app.get("last_scanned")
                or previous_positive_scan.get("last_scanned")
                or previous_app.get("last_verified")
                or app.get("first_verified_at")
                or app.get("last_scanned")
                or app.get("last_verified")
            )
        if not isinstance(first_verified_at, str) or not first_verified_at.strip():
            first_verified_at = generated_at
        app["first_verified_at"] = first_verified_at
        app["new_addition"] = package_name in new_packages

    scans = {
        package_name: scan
        for package_name, scan in previous_scans.items()
        if package_name in current_packages
    }
    for result in results:
        package_name = result["package_name"]
        status = result.get("status")
        if status in {"positive", "negative"}:
            scan = {
                "package_name": package_name,
                "category": result.get("category", ""),
                "satellite_optimized": result.get("satellite_optimized", False),
                "status": status,
                "last_scanned": result.get("last_scanned"),
            }
            previous_first_verified_at = (
                previous_scans.get(package_name, {}).get("first_verified_at")
                or previous.get(package_name, {}).get("first_verified_at")
                or previous.get(package_name, {}).get("last_scanned")
                or previous.get(package_name, {}).get("last_verified")
            )
            if previous_first_verified_at:
                scan["first_verified_at"] = previous_first_verified_at
            elif status == "positive":
                scan["first_verified_at"] = current_apps[package_name].get("first_verified_at")
            scans[package_name] = scan
        elif status == "error":
            previous_scan = scans.get(package_name)
            if previous_scan:
                scan = {
                    **previous_scan,
                    "last_error": result.get("error"),
                }
                if result.get("category"):
                    scan["category"] = result["category"]
                scans[package_name] = scan
            else:
                scans[package_name] = {
                    "package_name": package_name,
                    "category": result.get("category", ""),
                    "satellite_optimized": False,
                    "status": "error",
                    "last_scanned": None,
                    "last_error": result.get("error"),
                }

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
            "generated_at": generated_at,
            "total_apps": len(deduped),
            "new_additions": len(new_packages),
            "new_packages": sorted(new_packages),
            "total_scanned": len(scans),
            "summary": summary,
        },
        "apps": deduped,
        "scanned": {package_name: scans[package_name] for package_name in sorted(scans)},
    }

    _write_json_atomic(output_path, catalog)
    logger.info("Catalog written to %s (%d apps, %d new)", output_path, len(deduped), len(new_packages))


def _write_json_atomic(output_path: Path, data: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
            temporary_path = Path(tmp.name)
        os.replace(temporary_path, output_path)
    except OSError:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise


def _write_error_report(output_path: Path, failures: dict[str, dict]) -> None:
    not_found = [
        {
            "package_name": package_name,
            "error": failure.get("error", "package_not_found"),
            "detail": failure.get("detail"),
        }
        for package_name, failure in sorted(failures.items())
        if failure.get("error") == "package_not_found"
    ]
    errors = [
        {
            "package_name": package_name,
            "error": failure.get("error", "unknown_error"),
            "detail": failure.get("detail"),
        }
        for package_name, failure in sorted(failures.items())
        if failure.get("error") != "package_not_found"
    ]
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_failures": len(failures),
        "total_errors": len(errors),
        "packages_not_found": len(not_found),
        "not_found": not_found,
        "errors": errors,
    }

    _write_json_atomic(output_path, report)

    if failures:
        logger.info(
            "Error report written to %s (%d errors, %d packages not found)",
            output_path,
            len(errors),
            len(not_found),
        )


def _write_seed_validation_report(
    output_path: Path, entries: list[dict], enabled: bool = True
) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enabled": enabled,
        "total_checked": len(entries),
        "accepted_for_crawl": sum(entry["status"] != "rejected" for entry in entries),
        "rejected": sum(entry["status"] == "rejected" for entry in entries),
        "entries": entries,
    }
    _write_json_atomic(output_path, report)
    logger.info(
        "Seed validation written to %s (%d checked, %d rejected)",
        output_path,
        report["total_checked"],
        report["rejected"],
    )


def run_crawl(config: dict) -> dict:
    seed_path = config.get("seed_list_path", "seed_list.json")
    output_path = Path(config.get("output_path", "catalog.json"))
    error_output_path = Path(
        config.get("error_output_path", output_path.with_name("crawl-errors.json"))
    )
    validation_report_path = Path(
        config.get("seed_validation_report_path", output_path.with_name("seed-validation.json"))
    )
    output_paths = {
        "output_path": output_path.resolve(),
        "error_output_path": error_output_path.resolve(),
        "seed_validation_report_path": validation_report_path.resolve(),
    }
    if len(set(output_paths.values())) != len(output_paths):
        raise ValueError("catalog, error, and seed validation paths must differ")
    input_paths = {Path(seed_path).resolve()}
    if config.get("_config_path"):
        input_paths.add(Path(config["_config_path"]).resolve())
    if any(path in input_paths for path in output_paths.values()):
        raise ValueError("output paths must differ from seed and config paths")
    max_workers = config.get("crawler", {}).get("max_workers", 5)
    seed_list = _load_seed_list(seed_path)
    configure_parser_logging(config.get("quiet", False))

    logger.info("Starting crawl: %d apps, %d workers", len(seed_list), max_workers)

    previous = _load_previous_catalog(output_path)
    previous_scans = _load_previous_scan_state(output_path, previous)
    crawler_config = config.get("crawler", {})
    scan_days = crawler_config.get("scan_days", SCAN_DAYS_DEFAULT)
    entries_to_scan = [
        entry
        for entry in seed_list
        if not _is_scan_fresh(previous_scans.get(entry["package_name"]), scan_days)
    ]
    validation_rejected: dict[str, dict] = {}
    if config.get("validate_seed_packages", False):
        entries_to_scan, validation_rejected, validation_entries = _validate_seed_entries(
            entries_to_scan, config, max_workers
        )
        _write_seed_validation_report(validation_report_path, validation_entries)
        config["_validated_play_packages"] = {
            entry["package_name"]
            for entry in validation_entries
            if entry["status"] == "valid"
        }
    else:
        _write_seed_validation_report(validation_report_path, [], enabled=False)
    results: list[dict] = [
        {
            "package_name": entry["package_name"],
            "category": entry.get("category", ""),
            "satellite_optimized": previous_scans[entry["package_name"]].get(
                "satellite_optimized", False
            ),
            "status": "skipped",
            "error": None,
        }
        for entry in seed_list
        if entry["package_name"] in previous_scans
        and _is_scan_fresh(previous_scans[entry["package_name"]], scan_days)
    ]

    downloaded = 0
    sat_found = 0
    cached_skipped = 0
    failed_packages: set[str] = set()
    categories = {entry["package_name"]: entry.get("category", "") for entry in seed_list}
    failure_details: dict[str, dict] = {
        package_name: {
            "error": "package_not_found",
            "detail": result.get("detail"),
        }
        for package_name, result in validation_rejected.items()
    }
    errors = 0
    packages_not_found = len(validation_rejected)
    for result in validation_rejected.values():
        results.append(
            {
                "package_name": result["package_name"],
                "category": result.get("category", ""),
                "status": "error",
                "error": "package_not_found",
                "error_detail": result.get("detail"),
            }
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                process_package,
                entry["package_name"],
                entry.get("category", ""),
                config,
            ): entry["package_name"]
            for entry in entries_to_scan
        }

        for future in as_completed(future_map):
            pkg = future_map[future]
            try:
                result = future.result()
                if not result.get("category"):
                    result["category"] = categories.get(pkg, "")
                if result.get("error"):
                    errors += 1
                    failed_packages.add(pkg)
                    failure_details[pkg] = {
                        "error": result["error"],
                        "detail": result.get("error_detail"),
                    }
                results.append(result)
                if result.get("downloaded"):
                    downloaded += 1
                if (
                    result.get("cached")
                    and not result.get("downloaded")
                    and not result.get("error")
                ):
                    cached_skipped += 1
                if result.get("satellite_optimized") and result.get("status") != "skipped":
                    sat_found += 1
            except Exception as e:
                errors += 1
                failed_packages.add(pkg)
                logger.error("Unhandled exception for %s: %s", pkg, e)
                failure_details[pkg] = {"error": "unhandled_exception", "detail": str(e)}
                results.append(
                    {
                        "package_name": pkg,
                        "category": categories.get(pkg, ""),
                        "status": "error",
                        "error": str(e),
                        "error_detail": str(e),
                    }
                )

    summary = {
        "total_processed": len(seed_list),
        "scanned_this_run": len(entries_to_scan),
        "scan_skipped": len(seed_list) - len(entries_to_scan) - len(validation_rejected),
        "downloaded": downloaded,
        "satellite_optimized_found": sat_found,
        "errors": errors,
        "packages_not_found": packages_not_found,
        "total_failures": errors + packages_not_found,
        "cached_skipped": cached_skipped,
        "seed_validation_rejected": packages_not_found,
    }

    logger.info(
        "Crawl complete: %d scanned, %d skipped, %d downloaded, %d sat-optimized, "
        "%d errors, %d packages not found",
        summary["scanned_this_run"],
        summary["scan_skipped"],
        summary["downloaded"],
        summary["satellite_optimized_found"],
        summary["errors"],
        summary["packages_not_found"],
    )

    _write_catalog(
        output_path,
        results,
        previous,
        previous_scans,
        summary,
        failed_packages,
        {entry["package_name"] for entry in seed_list},
    )

    _write_error_report(error_output_path, failure_details)

    return summary


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("config.yaml")
    try:
        config = load_config(config_path)
        config_dir = config_path.resolve().parent
        config["_config_path"] = str(config_path.resolve())
        for key in (
            "seed_list_path",
            "output_path",
            "apk_cache_dir",
            "error_output_path",
            "seed_validation_report_path",
        ):
            raw_value = config.get(key)
            if raw_value:
                value = Path(raw_value)
                if not value.is_absolute():
                    config[key] = str(config_dir / value)
    except Exception as e:
        logger.error("Failed to load config %s: %s", config_path, e)
        sys.exit(1)

    _setup_logging(config.get("log_level", "INFO"))

    summary = run_crawl(config)

    if summary.get("total_failures", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

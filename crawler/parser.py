from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Optional

from androguard.core.apk import APK

try:
    from loguru import logger as _androguard_logger

    _androguard_logger.remove()
    _androguard_logger.add(sys.stderr, level="WARNING")
except ImportError:
    _androguard_logger = None

logger = logging.getLogger(__name__)

SATELLITE_FLAG = "android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED"
CACHE_FILE = ".parser_cache.json"
CACHE_LOCK = threading.Lock()
MAX_EXTRACTED_APK_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


def configure_parser_logging(quiet: bool) -> None:
    if _androguard_logger is None:
        return
    if quiet:
        _androguard_logger.disable("androguard")
    else:
        _androguard_logger.enable("androguard")


def _cache_path(apk_path: Path) -> Path:
    return apk_path.parent / CACHE_FILE


def _load_cache(apk_path: Path) -> dict:
    cache_file = _cache_path(apk_path)
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(apk_path: Path, cache: dict) -> None:
    cache_file = _cache_path(apk_path)
    try:
        with CACHE_LOCK:
            current = _load_cache(apk_path)
            current.update(cache)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=cache_file.parent,
                prefix=f".{cache_file.name}.",
                delete=False,
            ) as tmp:
                json.dump(current, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                temporary_path = Path(tmp.name)
            os.replace(temporary_path, cache_file)
    except OSError as e:
        logger.warning("Failed to write parser cache: %s", e)


def _apk_hash(apk_path: Path) -> str:
    h = hashlib.sha256()
    with open(apk_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_fingerprint(apk_path: Path) -> dict[str, int]:
    stat = apk_path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "inode": stat.st_ino,
    }


def _manifest_contains_satellite_flag(apk_path: Path) -> Optional[bool]:
    """Return a cheap manifest prefilter result, or None when it cannot decide."""
    try:
        with zipfile.ZipFile(apk_path) as archive:
            manifest = archive.getinfo("AndroidManifest.xml")
            if manifest.file_size > MAX_MANIFEST_BYTES:
                return None
            data = archive.read(manifest)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None

    return (
        SATELLITE_FLAG.encode("utf-8") in data
        or SATELLITE_FLAG.encode("utf-16le") in data
    )


def _is_xapk(path: Path) -> bool:
    return path.suffix.lower() in (".xapk", ".apks")


def _extract_base_apk_from_xapk(xapk_path: Path, output_dir: Path) -> Optional[Path]:
    try:
        with zipfile.ZipFile(xapk_path) as zf:
            entries = zf.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                logger.warning("Rejected XAPK with too many entries: %s", xapk_path.name)
                return None
            if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                logger.warning("Rejected oversized XAPK archive: %s", xapk_path.name)
                return None
            base_name = _find_base_member(zf)
            if not base_name:
                logger.warning("No base APK found in XAPK: %s", xapk_path.name)
                return None

            member = zf.getinfo(base_name)
            if member.is_dir() or member.file_size > MAX_EXTRACTED_APK_BYTES:
                logger.warning("Rejected oversized or non-file base APK: %s", base_name)
                return None

            output_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(base_name).name
            base_path = output_dir / f".{xapk_path.stem}-base-{safe_name}"
            with zf.open(member) as src, base_path.open("wb") as dst:
                copied = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > MAX_EXTRACTED_APK_BYTES:
                        base_path.unlink(missing_ok=True)
                        logger.warning("Rejected oversized base APK: %s", base_name)
                        return None
                    dst.write(chunk)
            logger.info("Extracted base APK %s from XAPK %s", base_name, xapk_path.name)
            return base_path
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        logger.error("Failed to extract XAPK %s: %s", xapk_path.name, e)
        return None


def _find_base_member(archive: zipfile.ZipFile) -> Optional[str]:
    names = [info.filename for info in archive.infolist() if not info.is_dir()]
    apk_names = [name for name in names if name.lower().endswith(".apk")]
    if not apk_names:
        return None

    try:
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            return None
        manifest_data = json.loads(archive.read(manifest_info))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
        manifest_data = {}
    if not isinstance(manifest_data, dict):
        manifest_data = {}

    candidates: list[tuple[int, str]] = []
    entries = manifest_data.get("entries", [])
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, str):
                candidates.append((1, entry))
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("file")
                if name:
                    priority = 0 if entry.get("type") == "base" else 1
                    candidates.append((priority, name))

    for name in manifest_data.get("split_apks", []) if isinstance(manifest_data, dict) else []:
        if isinstance(name, str):
            candidates.append((0 if Path(name).name == "base.apk" else 1, name))

    candidates.extend((0 if Path(name).name.lower() == "base.apk" else 2, name) for name in apk_names)
    for _, name in sorted(candidates, key=lambda item: item[0]):
        if name not in names or not _safe_archive_member(name):
            continue
        if Path(name).name.lower() == "base.apk" or name in apk_names:
            return name
    return None


def _safe_archive_member(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def parse_apk(apk_path: Path) -> dict:
    apk_path = Path(apk_path)
    if not apk_path.exists():
        logger.error("APK not found: %s", apk_path)
        return {"satellite_optimized": False, "app_name": "", "package_name": "", "icon_path": None, "error": "file_not_found"}

    cache = _load_cache(apk_path)
    try:
        fingerprint = _file_fingerprint(apk_path)
    except OSError as e:
        # Keep malformed test fixtures and legacy cache entries on the full-parse path.
        fingerprint = None

    cached = cache.get(str(apk_path.name))
    if cached:
        if fingerprint and cached.get("fingerprint") == fingerprint:
            logger.debug("Using cached parse result for %s", apk_path.name)
            return cached["result"]
        if cached.get("hash"):
            try:
                if cached["hash"] == _apk_hash(apk_path):
                    logger.debug("Using legacy cached parse result for %s", apk_path.name)
                    return cached["result"]
            except OSError:
                pass

    if _is_xapk(apk_path):
        logger.info("Detected XAPK format: %s", apk_path.name)
        extracted = _extract_base_apk_from_xapk(apk_path, apk_path.parent)
        if not extracted:
            return {"satellite_optimized": False, "app_name": "", "package_name": "", "icon_path": None, "error": "xapk_extraction_failed"}
        result = parse_apk(extracted)
        try:
            extracted.unlink()
        except OSError:
            pass
        return result

    prefilter = _manifest_contains_satellite_flag(apk_path)
    if prefilter is False:
        result = {
            "satellite_optimized": False,
            "app_name": "",
            "package_name": None,
            "icon_path": None,
            "error": None,
        }
        if fingerprint:
            cache[str(apk_path.name)] = {"fingerprint": fingerprint, "result": result}
            _save_cache(apk_path, cache)
        return result

    try:
        a = APK(str(apk_path))
        package_name = a.get_package()
        has_flag = _check_satellite_flag(a, package_name)
    except Exception as e:
        logger.error("Failed to parse APK %s: %s", apk_path.name, e)
        return {
            "satellite_optimized": False,
            "app_name": "",
            "package_name": "",
            "icon_path": None,
            "error": str(e),
        }

    try:
        app_name = a.get_app_name()
    except Exception as e:
        logger.warning("Failed to read app name from %s: %s", apk_path.name, e)
        app_name = package_name
    try:
        icon_path = a.get_app_icon()
    except Exception as e:
        logger.warning("Failed to read icon from %s: %s", apk_path.name, e)
        icon_path = None

    result = {
        "satellite_optimized": has_flag,
        "app_name": app_name or package_name,
        "package_name": package_name,
        "icon_path": icon_path,
        "error": None,
    }

    if fingerprint:
        cache[str(apk_path.name)] = {"fingerprint": fingerprint, "result": result}
        _save_cache(apk_path, cache)

    return result


def _check_satellite_flag(apk: APK, package_name: Optional[str] = None) -> bool:
    manifest_xml = apk.get_android_manifest_xml()
    if manifest_xml is None:
        logger.warning("No AndroidManifest.xml found")
        return False

    ns = {"android": "http://schemas.android.com/apk/res/android"}

    for meta_data in manifest_xml.iter("meta-data"):
        name = meta_data.get("{%s}name" % ns["android"])
        if name == SATELLITE_FLAG:
            value = meta_data.get("{%s}value" % ns["android"])
            logger.info("Found satellite flag in manifest: value=%s", value)
            if package_name is None:
                package_name = apk.get_package()
            return isinstance(package_name, str) and value == package_name

    return False


def check_satellite_flag(apk_path: Path) -> bool:
    result = parse_apk(apk_path)
    return result.get("satellite_optimized", False)

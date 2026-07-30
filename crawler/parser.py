from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from pathlib import Path
from typing import Optional

from androguard.core.apk import APK

logger = logging.getLogger(__name__)

SATELLITE_FLAG = "android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED"
CACHE_FILE = ".parser_cache.json"


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
        cache_file.write_text(json.dumps(cache, indent=2))
    except OSError as e:
        logger.warning("Failed to write parser cache: %s", e)


def _apk_hash(apk_path: Path) -> str:
    h = hashlib.sha256()
    with open(apk_path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()[:16]


def _is_xapk(path: Path) -> bool:
    return path.suffix.lower() in (".xapk", ".apks")


def _extract_base_apk_from_xapk(xapk_path: Path, output_dir: Path) -> Optional[Path]:
    try:
        with zipfile.ZipFile(xapk_path) as zf:
            manifest_data = json.loads(zf.read("manifest.json"))
            entries = manifest_data.get("entries", [])
            for entry in entries:
                if entry.get("type") == "base" or entry.get("name", "").startswith("base"):
                    base_name = entry["name"]
                    base_path = output_dir / base_name
                    with zf.open(base_name) as src, open(base_path, "wb") as dst:
                        dst.write(src.read())
                    logger.info("Extracted base APK %s from XAPK %s", base_name, xapk_path.name)
                    return base_path
            logger.warning("No base APK found in XAPK manifest: %s", xapk_path.name)
            return None
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        logger.error("Failed to extract XAPK %s: %s", xapk_path.name, e)
        return None


def parse_apk(apk_path: Path) -> dict:
    apk_path = Path(apk_path)
    if not apk_path.exists():
        logger.error("APK not found: %s", apk_path)
        return {"satellite_optimized": False, "app_name": "", "package_name": "", "icon_path": None, "error": "file_not_found"}

    cache = _load_cache(apk_path.parent)
    file_hash = _apk_hash(apk_path)

    cached = cache.get(str(apk_path.name))
    if cached and cached.get("hash") == file_hash:
        logger.debug("Using cached parse result for %s", apk_path.name)
        return cached["result"]

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

    try:
        a = APK(str(apk_path))
    except Exception as e:
        logger.error("Failed to parse APK %s: %s", apk_path.name, e)
        return {"satellite_optimized": False, "app_name": "", "package_name": "", "icon_path": None, "error": str(e)}

    package_name = a.get_package()
    app_name = a.get_app_name()
    icon_path = a.get_app_icon()

    has_flag = _check_satellite_flag(a)

    result = {
        "satellite_optimized": has_flag,
        "app_name": app_name or package_name,
        "package_name": package_name,
        "icon_path": icon_path,
        "error": None,
    }

    cache[str(apk_path.name)] = {"hash": file_hash, "result": result}
    _save_cache(apk_path.parent, cache)

    return result


def _check_satellite_flag(apk: APK) -> bool:
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
            return True

    return False


def check_satellite_flag(apk_path: Path) -> bool:
    result = parse_apk(apk_path)
    return result.get("satellite_optimized", False)

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SATELLITE_FLAG = "android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED"
CACHE_FILE = ".parser_cache.json"
CACHE_LOCK = threading.Lock()
AAPT2_COMMAND = os.environ.get("AAPT2_PATH", "aapt2")
AAPT2_TIMEOUT_SECONDS = 60
MAX_EXTRACTED_APK_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


def configure_parser_logging(quiet: bool) -> None:
    # Kept as a compatibility hook for the crawler; aapt2 owns parser logging.
    return


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
    base_path = None
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
        if base_path:
            base_path.unlink(missing_ok=True)
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


def _aapt_attribute(line: str) -> tuple[Optional[str], Optional[str]]:
    """Extract an attribute's local name and quoted value from xmltree output."""
    stripped = line.strip()
    if not stripped.startswith("A:"):
        return None, None
    attribute, separator, value = stripped[2:].partition("=")
    if not separator:
        return None, None
    local_name = attribute.split("(", 1)[0].rsplit(":", 1)[-1].strip()
    value = value.strip()
    if value.startswith('"'):
        end_quote = value.find('"', 1)
        return local_name, value[1:end_quote] if end_quote > 0 else None
    return local_name, value.split(None, 1)[0] if value else None


def _parse_aapt_xmltree(output: str) -> dict:
    package_name = None
    satellite_optimized = False
    lines = output.splitlines()

    for line in lines:
        name, value = _aapt_attribute(line)
        if name == "package" and value and package_name is None:
            package_name = value

    for index, line in enumerate(lines):
        if not line.lstrip().startswith("E: meta-data"):
            continue
        element_indent = len(line) - len(line.lstrip())
        attributes = {}
        for child_line in lines[index + 1 :]:
            if child_line.strip() and len(child_line) - len(child_line.lstrip()) <= element_indent:
                break
            name, value = _aapt_attribute(child_line)
            if name and value is not None:
                attributes[name] = value
        if (
            attributes.get("name") == SATELLITE_FLAG
            and attributes.get("value") == package_name
        ):
            satellite_optimized = True
            break

    return {
        "package_name": package_name,
        "satellite_optimized": satellite_optimized,
    }


def _parse_aapt_badging(output: str) -> dict:
    package_match = re.search(r"^package: name='([^']+)'", output, re.MULTILINE)
    label_match = re.search(r"^application-label:'([^']*)'", output, re.MULTILINE)
    icon_match = re.search(r"^application: label='[^']*' icon='([^']*)'", output, re.MULTILINE)
    return {
        "package_name": package_match.group(1) if package_match else None,
        "app_name": label_match.group(1) if label_match else "",
        "icon_path": icon_match.group(1) if icon_match else None,
    }


def _run_aapt2_dump(args: list[str], apk_path: Path, timeout: float) -> str:
    try:
        completed = subprocess.run(
            [AAPT2_COMMAND, "dump", *args, str(apk_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"aapt2 executable not found: {AAPT2_COMMAND}") from e
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(f"aapt2 timed out parsing {apk_path.name}") from e
    except OSError as e:
        raise RuntimeError(f"Could not execute aapt2: {e}") from e

    if completed.returncode != 0:
        detail = completed.stderr.strip() or "unknown aapt2 error"
        raise RuntimeError(detail)
    return completed.stdout


def _parse_apk_with_aapt2(apk_path: Path, timeout: float) -> dict:
    prefilter = _manifest_contains_satellite_flag(apk_path)
    if prefilter is False:
        return {
            "satellite_optimized": False,
            "app_name": "",
            "package_name": None,
            "icon_path": None,
            "error": None,
        }

    deadline = time.monotonic() + timeout
    manifest = _parse_aapt_xmltree(
        _run_aapt2_dump(
            ["xmltree", "--file", "AndroidManifest.xml"],
            apk_path,
            max(0.001, deadline - time.monotonic()),
        )
    )
    package_name = manifest.get("package_name")
    if not package_name:
        raise RuntimeError("aapt2 did not return a manifest package name")
    if not manifest["satellite_optimized"]:
        return {
            "satellite_optimized": False,
            "app_name": "",
            "package_name": package_name,
            "icon_path": None,
            "error": None,
        }

    badging = _parse_aapt_badging(
        _run_aapt2_dump(
            ["badging"],
            apk_path,
            max(0.001, deadline - time.monotonic()),
        )
    )
    return {
        "satellite_optimized": True,
        "app_name": badging.get("app_name") or package_name,
        "package_name": badging.get("package_name") or package_name,
        "icon_path": badging.get("icon_path"),
        "error": None,
    }


def parse_apk(apk_path: Path, timeout: float = AAPT2_TIMEOUT_SECONDS) -> dict:
    apk_path = Path(apk_path)
    if not apk_path.exists():
        logger.error("APK not found: %s", apk_path)
        return {"satellite_optimized": False, "app_name": "", "package_name": "", "icon_path": None, "error": "file_not_found"}

    cache = _load_cache(apk_path)
    try:
        fingerprint = _file_fingerprint(apk_path)
    except OSError:
        # Keep malformed test fixtures and legacy cache entries on the full-parse path.
        fingerprint = None

    cached = cache.get(str(apk_path.name))
    if cached:
        cached_result = cached.get("result", {})
        if fingerprint and cached.get("fingerprint") == fingerprint:
            if not cached_result.get("error"):
                logger.debug("Using cached parse result for %s", apk_path.name)
                return cached_result
        if cached.get("hash"):
            try:
                if cached["hash"] == _apk_hash(apk_path):
                    if not cached_result.get("error"):
                        logger.debug("Using legacy cached parse result for %s", apk_path.name)
                        return cached_result
            except OSError:
                pass

    try:
        if _is_xapk(apk_path):
            logger.info("Detected XAPK format: %s", apk_path.name)
            extracted = _extract_base_apk_from_xapk(apk_path, apk_path.parent)
            if not extracted:
                return {"satellite_optimized": False, "app_name": "", "package_name": "", "icon_path": None, "error": "xapk_extraction_failed"}
            try:
                result = _parse_apk_with_aapt2(extracted, timeout)
            finally:
                extracted.unlink(missing_ok=True)
        else:
            result = _parse_apk_with_aapt2(apk_path, timeout)
    except (RuntimeError, TimeoutError) as e:
        logger.error("Failed to parse APK %s: %s", apk_path.name, e)
        return {
            "satellite_optimized": False,
            "app_name": "",
            "package_name": "",
            "icon_path": None,
            "error": str(e),
        }

    if fingerprint and not result.get("error"):
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

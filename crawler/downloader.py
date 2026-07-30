from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from justapk import APKDownloader

logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _configure_proxy(config: dict) -> None:
    proxy = config.get("proxy", {})
    if not proxy.get("enabled", False):
        return
    scheme = proxy.get("scheme", "socks5")
    host = proxy.get("host", "127.0.0.1")
    port = proxy.get("port", 1080)
    proxy_url = f"{scheme}://{host}:{port}"
    os.environ.setdefault("ALL_PROXY", proxy_url)
    os.environ.setdefault("HTTP_PROXY", proxy_url)
    os.environ.setdefault("HTTPS_PROXY", proxy_url)
    logger.info("Proxy configured: %s", proxy_url)


def download(
    package_name: str,
    output_dir: Optional[Path] = None,
    config: Optional[dict] = None,
) -> Optional[Path]:
    if not package_name or not package_name.strip() or "." not in package_name:
        logger.warning("Invalid package name: '%s'", package_name)
        return None

    if config is None:
        config = load_config()

    if output_dir is None:
        output_dir = Path(config.get("apk_cache_dir", "apk_cache"))

    _configure_proxy(config)

    source_order = config.get("source_order")
    sources = source_order if source_order else None

    per_app_timeout = config.get("crawler", {}).get("per_app_timeout", 180)

    import signal

    class TimeoutError(Exception):
        pass

    def timeout_handler(_signum, _frame):
        raise TimeoutError(f"Download timed out after {per_app_timeout}s")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(per_app_timeout)

    dl = APKDownloader(sources=sources, auto_convert_xapk=True)
    try:
        logger.info("Downloading %s ...", package_name)
        result = dl.download(package_name, output_dir=output_dir)
        signal.alarm(0)
        if result and result.path:
            logger.info("Downloaded %s -> %s (%.1f MB)", package_name, result.path, result.size / 1e6)
            return Path(result.path)
        return None
    except TimeoutError:
        logger.error("Timeout downloading %s after %ds", package_name, per_app_timeout)
        return None
    except Exception as e:
        logger.warning("Failed to download %s: %s", package_name, e)
        return None
    finally:
        signal.alarm(0)


def get_app_info(
    package_name: str,
    config: Optional[dict] = None,
) -> Optional[dict]:
    if not package_name or not package_name.strip():
        return None

    if config is None:
        config = load_config()

    _configure_proxy(config)

    dl = APKDownloader()
    try:
        info = dl.info(package_name)
        if info:
            return {
                "package_name": info.package,
                "app_name": info.name,
                "version": info.version,
                "icon_url": getattr(info, "icon_url", None),
                "source": info.source,
            }
        return None
    except Exception as e:
        logger.debug("Info lookup failed for %s: %s", package_name, e)
        return None

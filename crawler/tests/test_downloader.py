from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from downloader import download, get_app_info

MOCK_CONFIG = {
    "apk_cache_dir": "apk_cache",
    "source_order": ["apkpure", "fdroid"],
    "crawler": {
        "per_app_timeout": 10,
    },
    "proxy": {"enabled": False},
}


class TestDownload:
    def test_invalid_empty_string(self):
        result = download("", config=MOCK_CONFIG)
        assert result is None

    def test_invalid_no_dot(self):
        result = download("notapackagename", config=MOCK_CONFIG)
        assert result is None

    def test_invalid_package_shape(self):
        for package_name in ("com..example", "../com.example", "com/example.app"):
            assert download(package_name, config=MOCK_CONFIG) is None

    def test_invalid_whitespace(self):
        result = download("   ", config=MOCK_CONFIG)
        assert result is None

    @patch("downloader.APKDownloader")
    def test_all_sources_fail(self, MockDownloader):
        mock_instance = MockDownloader.return_value
        mock_instance.download.side_effect = RuntimeError("All sources failed")
        result = download("com.nonexistent.fakeapp", config=MOCK_CONFIG)
        assert result is None

    @patch("downloader.APKDownloader")
    def test_happy_path(self, MockDownloader):
        mock_instance = MockDownloader.return_value
        mock_result = type("Result", (), {"path": Path("/tmp/apks/org.telegram.messenger.apk"), "size": 50_000_000, "sha256": "abc"})()
        mock_instance.download.return_value = mock_result

        with tempfile.TemporaryDirectory() as tmp:
            mock_result.path = Path(tmp) / "org.telegram.messenger.apk"
            result = download("org.telegram.messenger", output_dir=Path(tmp), config=MOCK_CONFIG)
            assert result is not None
            assert str(result).endswith(".apk")

    @patch("downloader.APKDownloader")
    def test_download_returns_none_on_exception(self, MockDownloader):
        mock_instance = MockDownloader.return_value
        mock_instance.download.side_effect = Exception("Connection error")
        result = download("org.telegram.messenger", config=MOCK_CONFIG)
        assert result is None


class TestGetAppInfo:
    @patch("downloader.APKDownloader")
    def test_returns_info(self, MockDownloader):
        mock_instance = MockDownloader.return_value
        MockInfo = type("AppInfo", (), {"package": "com.example.app", "name": "Example App", "version": "1.0", "icon_url": "https://example.com/icon.png", "source": "apkpure"})
        mock_instance.info.return_value = MockInfo

        info = get_app_info("com.example.app", config=MOCK_CONFIG)
        assert info is not None
        assert info["package_name"] == "com.example.app"
        assert info["app_name"] == "Example App"

    @patch("downloader.APKDownloader")
    def test_returns_none_on_failure(self, MockDownloader):
        mock_instance = MockDownloader.return_value
        mock_instance.info.return_value = None
        info = get_app_info("com.nonexistent.app", config=MOCK_CONFIG)
        assert info is None

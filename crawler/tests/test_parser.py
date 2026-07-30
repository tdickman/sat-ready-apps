from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from parser import (
    _check_satellite_flag,
    _extract_base_apk_from_xapk,
    _is_xapk,
    check_satellite_flag,
    parse_apk,
    SATELLITE_FLAG,
)


class TestIsXapk:
    def test_xapk_suffix(self):
        assert _is_xapk(Path("app.xapk")) is True

    def test_apks_suffix(self):
        assert _is_xapk(Path("app.apks")) is True

    def test_apk_suffix(self):
        assert _is_xapk(Path("app.apk")) is False

    def test_unknown_suffix(self):
        assert _is_xapk(Path("app.zip")) is False


class TestCheckSatelliteFlag:
    def test_flag_found(self):
        flag_elem = MagicMock()
        flag_elem.get.side_effect = lambda key: {
            "{http://schemas.android.com/apk/res/android}name": SATELLITE_FLAG,
            "{http://schemas.android.com/apk/res/android}value": "com.example.app",
        }.get(key)

        mock_root = MagicMock()
        mock_root.iter.return_value = [flag_elem]

        mock_apk = MagicMock()
        mock_apk.get_android_manifest_xml.return_value = mock_root

        assert _check_satellite_flag(mock_apk) is True

    def test_flag_not_found(self):
        other = MagicMock()
        other.get.side_effect = lambda key: {
            "{http://schemas.android.com/apk/res/android}name": "some.other.flag",
            "{http://schemas.android.com/apk/res/android}value": "x",
        }.get(key)

        mock_root = MagicMock()
        mock_root.iter.return_value = [other]

        mock_apk = MagicMock()
        mock_apk.get_android_manifest_xml.return_value = mock_root

        assert _check_satellite_flag(mock_apk) is False

    def test_no_manifest(self):
        mock_apk = MagicMock()
        mock_apk.get_android_manifest_xml.return_value = None
        assert _check_satellite_flag(mock_apk) is False


@patch("parser.Path.exists", return_value=True)
@patch("parser._load_cache", side_effect=lambda _: {})
@patch("parser._save_cache")
@patch("parser._apk_hash", return_value="abc123")
class TestParseApk:
    @patch("parser.APK")
    def test_satellite_flag_present(self, MockAPK, mock_hash, mock_save, mock_load, mock_exists):
        mock_apk = MagicMock()
        mock_apk.get_package.return_value = "com.example.app"
        mock_apk.get_app_name.return_value = "Example App"
        mock_apk.get_app_icon.return_value = "res/mipmap/ic_launcher.png"

        flag_elem = MagicMock()
        flag_elem.get.side_effect = lambda key: {
            "{http://schemas.android.com/apk/res/android}name": SATELLITE_FLAG,
            "{http://schemas.android.com/apk/res/android}value": "com.example.app",
        }.get(key)

        mock_root = MagicMock()
        mock_root.iter.return_value = [flag_elem]

        mock_apk.get_android_manifest_xml.return_value = mock_root
        MockAPK.return_value = mock_apk

        result = parse_apk(Path("/tmp/test.apk"))
        assert result["satellite_optimized"] is True
        assert result["app_name"] == "Example App"
        assert result["package_name"] == "com.example.app"

    @patch("parser.APK")
    def test_no_satellite_flag(self, MockAPK, mock_hash, mock_save, mock_load, mock_exists):
        mock_apk = MagicMock()
        mock_apk.get_package.return_value = "com.example.app"
        mock_apk.get_app_name.return_value = "Example App"
        mock_apk.get_app_icon.return_value = "res/mipmap/ic_launcher.png"

        other_elem = MagicMock()
        other_elem.get.side_effect = lambda key: {
            "{http://schemas.android.com/apk/res/android}name": "com.google.android.meta.different_flag",
            "{http://schemas.android.com/apk/res/android}value": "something",
        }.get(key)

        mock_root = MagicMock()
        mock_root.iter.return_value = [other_elem]

        mock_apk.get_android_manifest_xml.return_value = mock_root
        MockAPK.return_value = mock_apk

        result = parse_apk(Path("/tmp/test.apk"))
        assert result["satellite_optimized"] is False

    @patch("parser.APK")
    def test_no_manifest(self, MockAPK, mock_hash, mock_save, mock_load, mock_exists):
        mock_apk = MagicMock()
        mock_apk.get_android_manifest_xml.return_value = None
        MockAPK.return_value = mock_apk

        result = parse_apk(Path("/tmp/test.apk"))
        assert result["satellite_optimized"] is False

    @patch("parser.APK")
    def test_corrupted_apk(self, MockAPK, mock_hash, mock_save, mock_load, mock_exists):
        MockAPK.side_effect = Exception("Bad ZIP file")
        result = parse_apk(Path("/tmp/test.apk"))
        assert result["satellite_optimized"] is False
        assert result["error"] is not None


class TestParseApkNoMocks:
    def test_file_not_found(self):
        result = parse_apk(Path("/tmp/nonexistent.apk"))
        assert result["satellite_optimized"] is False
        assert result["error"] == "file_not_found"


class TestCheckSatelliteFlagTop:
    @patch("parser.parse_apk")
    def test_returns_true_when_optimized(self, mock_parse):
        mock_parse.return_value = {"satellite_optimized": True}
        assert check_satellite_flag(Path("/tmp/test.apk")) is True

    @patch("parser.parse_apk")
    def test_returns_false_when_not_optimized(self, mock_parse):
        mock_parse.return_value = {"satellite_optimized": False}
        assert check_satellite_flag(Path("/tmp/test.apk")) is False


class TestExtractXapk:
    def test_extract_base_apk(self, tmp_path):
        xapk_path = tmp_path / "test.xapk"
        manifest = {
            "entries": [
                {"name": "config.arm64_v8a.apk", "type": "native"},
                {"name": "base.apk", "type": "base"},
                {"name": "assets.apk", "type": "assets"},
            ]
        }
        with zipfile.ZipFile(xapk_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("base.apk", b"fake apk content")

        result = _extract_base_apk_from_xapk(xapk_path, tmp_path)
        assert result is not None
        assert result.name == "base.apk"
        assert result.read_bytes() == b"fake apk content"

    def test_extract_no_base_entry(self, tmp_path):
        xapk_path = tmp_path / "test.xapk"
        manifest = {"entries": [{"name": "config.apk", "type": "native"}]}
        with zipfile.ZipFile(xapk_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))

        result = _extract_base_apk_from_xapk(xapk_path, tmp_path)
        assert result is None

    def test_extract_corrupted_xapk(self, tmp_path):
        xapk_path = tmp_path / "corrupt.xapk"
        xapk_path.write_bytes(b"not a zip file")
        result = _extract_base_apk_from_xapk(xapk_path, tmp_path)
        assert result is None

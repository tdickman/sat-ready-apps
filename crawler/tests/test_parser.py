from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from parser import (
    _extract_base_apk_from_xapk,
    _is_xapk,
    _manifest_contains_satellite_flag,
    _parse_aapt_badging,
    _parse_aapt_xmltree,
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


class TestManifestPrefilter:
    def test_detects_utf8_flag(self, tmp_path):
        apk_path = tmp_path / "no-flag.apk"
        with zipfile.ZipFile(apk_path, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"prefix" + SATELLITE_FLAG.encode("utf-8"))

        assert _manifest_contains_satellite_flag(apk_path) is True

    def test_detects_utf16_flag(self, tmp_path):
        apk_path = tmp_path / "utf16.apk"
        with zipfile.ZipFile(apk_path, "w") as archive:
            archive.writestr("AndroidManifest.xml", SATELLITE_FLAG.encode("utf-16le"))

        assert _manifest_contains_satellite_flag(apk_path) is True

    def test_rejects_manifest_without_flag(self, tmp_path):
        apk_path = tmp_path / "no-flag.apk"
        with zipfile.ZipFile(apk_path, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"ordinary manifest")

        assert _manifest_contains_satellite_flag(apk_path) is False

    def test_unknown_archive_falls_back_to_full_parser(self, tmp_path):
        apk_path = tmp_path / "not-a-zip.apk"
        apk_path.write_bytes(b"not a zip")

        assert _manifest_contains_satellite_flag(apk_path) is None


XMLTREE_WITH_FLAG = f'''\
    E: manifest (line=1)
      A: package="com.example.app" (Raw: "com.example.app")
        E: application (line=1)
          E: meta-data (line=1)
            A: http://schemas.android.com/apk/res/android:name(0x01010003)="{SATELLITE_FLAG}"
            A: http://schemas.android.com/apk/res/android:value(0x01010024)="com.example.app"
'''

BADGING = """\
package: name='com.example.app' versionName='1.0'
application-label:'Example App'
application: label='Example App' icon='res/mipmap/ic_launcher.png'
"""


def test_aapt_xmltree_detects_satellite_flag():
    result = _parse_aapt_xmltree(XMLTREE_WITH_FLAG)
    assert result == {"package_name": "com.example.app", "satellite_optimized": True}


def test_aapt_xmltree_rejects_wrong_package_value():
    output = XMLTREE_WITH_FLAG.replace(
        'A: package="com.example.app"',
        'A: package="com.other.app"',
    )
    result = _parse_aapt_xmltree(output)
    assert result["package_name"] == "com.other.app"
    assert result["satellite_optimized"] is False


def test_aapt_badging_extracts_metadata():
    assert _parse_aapt_badging(BADGING) == {
        "package_name": "com.example.app",
        "app_name": "Example App",
        "icon_path": "res/mipmap/ic_launcher.png",
    }


def test_parse_apk_uses_aapt2_for_positive_result(tmp_path):
    apk_path = tmp_path / "test.apk"
    apk_path.write_bytes(b"apk")

    with patch("parser._manifest_contains_satellite_flag", return_value=True), patch(
        "parser._run_aapt2_dump", side_effect=[XMLTREE_WITH_FLAG, BADGING]
    ), patch("parser._save_cache"):
        result = parse_apk(apk_path)

    assert result == {
        "satellite_optimized": True,
        "app_name": "Example App",
        "package_name": "com.example.app",
        "icon_path": "res/mipmap/ic_launcher.png",
        "error": None,
    }


def test_parse_apk_skips_aapt2_for_manifest_without_flag(tmp_path):
    apk_path = tmp_path / "ordinary.apk"
    apk_path.write_bytes(b"apk")

    with patch("parser._manifest_contains_satellite_flag", return_value=False), patch(
        "parser._run_aapt2_dump"
    ) as run_aapt2, patch("parser._save_cache"):
        result = parse_apk(apk_path)

    assert result["satellite_optimized"] is False
    run_aapt2.assert_not_called()


def test_parse_apk_returns_aapt2_failure(tmp_path):
    apk_path = tmp_path / "broken.apk"
    apk_path.write_bytes(b"apk")

    with patch("parser._manifest_contains_satellite_flag", return_value=None), patch(
        "parser._run_aapt2_dump", side_effect=RuntimeError("bad manifest")
    ):
        result = parse_apk(apk_path)

    assert result["satellite_optimized"] is False
    assert result["error"] == "bad manifest"


def test_parse_apk_retries_transient_aapt2_failure(tmp_path):
    apk_path = tmp_path / "retry.apk"
    apk_path.write_bytes(b"apk")

    with patch("parser._manifest_contains_satellite_flag", return_value=True), patch(
        "parser._run_aapt2_dump",
        side_effect=[RuntimeError("temporary failure"), XMLTREE_WITH_FLAG, BADGING],
    ) as run_aapt2:
        first = parse_apk(apk_path)
        second = parse_apk(apk_path)

    assert first["error"] == "temporary failure"
    assert second["satellite_optimized"] is True
    assert run_aapt2.call_count == 3


def test_parse_reuses_fingerprint_cache_without_scanning_again(tmp_path):
    apk_path = tmp_path / "ordinary.apk"
    with zipfile.ZipFile(apk_path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"ordinary manifest")

    parse_apk(apk_path)
    with patch("parser._manifest_contains_satellite_flag") as prefilter:
        result = parse_apk(apk_path)

    assert result["satellite_optimized"] is False
    prefilter.assert_not_called()


def test_parse_caches_xapk_against_outer_archive(tmp_path):
    xapk_path = tmp_path / "test.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"entries": [{"name": "base.apk", "type": "base"}]}),
        )
        archive.writestr("base.apk", b"fake apk content")

    result = {
        "satellite_optimized": True,
        "app_name": "Example App",
        "package_name": "com.example.app",
        "icon_path": "res/icon.png",
        "error": None,
    }
    with patch("parser._parse_apk_with_aapt2", return_value=result) as parse:
        assert parse_apk(xapk_path) == result
        assert parse_apk(xapk_path) == result

    parse.assert_called_once()
    assert not list(tmp_path.glob(".*-base-*"))


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
        assert result.read_bytes() == b"fake apk content"

    def test_extract_no_base_entry(self, tmp_path):
        xapk_path = tmp_path / "test.xapk"
        manifest = {"entries": [{"name": "config.apk", "type": "native"}]}
        with zipfile.ZipFile(xapk_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))

        result = _extract_base_apk_from_xapk(xapk_path, tmp_path)
        assert result is None

    def test_extract_handles_non_object_manifest(self, tmp_path):
        xapk_path = tmp_path / "malformed.xapk"
        with zipfile.ZipFile(xapk_path, "w") as zf:
            zf.writestr("manifest.json", "[]")
            zf.writestr("base.apk", b"fake apk content")

        result = _extract_base_apk_from_xapk(xapk_path, tmp_path)
        assert result is not None
        assert result.read_bytes() == b"fake apk content"

    def test_extract_corrupted_xapk(self, tmp_path):
        xapk_path = tmp_path / "corrupt.xapk"
        xapk_path.write_bytes(b"not a zip file")
        result = _extract_base_apk_from_xapk(xapk_path, tmp_path)
        assert result is None

    def test_extract_rejects_path_traversal(self, tmp_path):
        xapk_path = tmp_path / "malicious.xapk"
        with zipfile.ZipFile(xapk_path, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps({"entries": [{"name": "../outside.apk", "type": "base"}]}),
            )
            zf.writestr("../outside.apk", b"must not be extracted")

        assert _extract_base_apk_from_xapk(xapk_path, tmp_path) is None
        assert not (tmp_path.parent / "outside.apk").exists()

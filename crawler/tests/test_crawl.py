from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from crawl import _build_store_urls, _find_cached_apk, _write_catalog, process_package, run_crawl


def test_find_cached_apk_requires_exact_package_prefix(tmp_path):
    (tmp_path / "com.google.android.apps.mapslite-1.apk").write_bytes(b"")
    (tmp_path / "com.google.android.apps.maps-1.apk.part").write_bytes(b"")
    expected = tmp_path / "com.google.android.apps.maps-2.apk"
    expected.write_bytes(b"")

    assert _find_cached_apk(tmp_path, "com.google.android.apps.maps") == expected


def test_write_catalog_filters_negative_results_and_preserves_failures(tmp_path):
    output_path = tmp_path / "catalog.json"
    previous = {
        "com.example.previous": {
            "package_name": "com.example.previous",
            "app_name": "Previous",
            "satellite_optimized": True,
        }
    }
    positive = {
        "package_name": "com.example.new",
        "app_name": "New",
        "satellite_optimized": True,
        "status": "positive",
        "last_verified": "2026-07-30",
    }
    negative = {
        "package_name": "com.example.negative",
        "satellite_optimized": False,
        "status": "negative",
    }

    _write_catalog(
        output_path,
        [positive, negative],
        previous,
        {},
        {},
        {"com.example.previous"},
        {"com.example.new", "com.example.negative", "com.example.previous"},
    )

    catalog = json.loads(output_path.read_text())
    packages = {app["package_name"] for app in catalog["apps"]}
    assert packages == {"com.example.new", "com.example.previous"}


def test_process_package_retries_a_corrupt_fresh_cache(tmp_path):
    cached_apk = tmp_path / "com.example.app-1.apk"
    cached_apk.write_bytes(b"cached")
    downloaded_apk = tmp_path / "com.example.app-2.apk"
    downloaded_apk.write_bytes(b"downloaded")
    config = {
        "apk_cache_dir": str(tmp_path),
        "crawler": {"cache_days": 30},
        "validate_store_links": False,
        "play_store_url_template": "https://play.google.com/store/apps/details?id={package_name}",
        "fdroid_url_template": "https://f-droid.org/packages/{package_name}/",
    }
    parser_results = [
        {"satellite_optimized": False, "error": "bad apk"},
        {
            "satellite_optimized": True,
            "package_name": "com.example.app",
            "app_name": "Example",
            "icon_path": None,
            "error": None,
        },
    ]

    with patch("crawl.parse_apk", side_effect=parser_results), patch(
        "crawl.download_with_diagnostics", return_value=(downloaded_apk, None)
    ), patch("crawl.get_app_info", return_value=None):
        result = process_package("com.example.app", "tools", config)

    assert result["status"] == "positive"
    assert result["downloaded"] is True


def test_process_package_reports_failed_replacement_download(tmp_path):
    cached_apk = tmp_path / "com.example.app-1.apk"
    cached_apk.write_bytes(b"cached")
    config = {
        "apk_cache_dir": str(tmp_path),
        "crawler": {"cache_days": 30},
    }

    with patch("crawl.parse_apk", return_value={"error": "bad apk"}), patch(
        "crawl.download_with_diagnostics",
        return_value=(None, "All sources failed: apkpure: timeout"),
    ):
        result = process_package("com.example.app", "tools", config)

    assert result["error"] == "download_failed"
    assert result["error_detail"] == "All sources failed: apkpure: timeout"


def test_run_crawl_does_not_count_failed_cache_refresh_as_skip(tmp_path):
    seed_path = tmp_path / "seed.json"
    output_path = tmp_path / "catalog.json"
    seed_path.write_text(json.dumps([{"package_name": "com.example.app"}]))
    result = {
        "package_name": "com.example.app",
        "error": "download_failed",
        "error_detail": "All sources failed: apkpure: timeout",
        "downloaded": False,
        "cached": True,
        "status": "error",
    }
    config = {
        "seed_list_path": str(seed_path),
        "output_path": str(output_path),
        "crawler": {"max_workers": 1},
    }

    with patch("crawl.process_package", return_value=result):
        summary = run_crawl(config)

    assert summary["errors"] == 1
    assert summary["cached_skipped"] == 0


def test_store_urls_only_include_available_links():
    config = {
        "validate_store_links": True,
        "play_store_url_template": "https://play.google.com/store/apps/details?id={package_name}",
        "fdroid_url_template": "https://f-droid.org/packages/{package_name}/",
    }
    with patch("crawl._store_url_is_available", side_effect=[True, False]):
        urls = _build_store_urls("com.example.app", config)

    assert urls["play_store_url"] is not None
    assert urls["fdroid_url"] is None


def test_store_urls_reuses_successful_seed_validation():
    config = {
        "validate_store_links": True,
        "_validated_play_packages": {"com.example.app"},
        "play_store_url_template": "https://play.google.com/store/apps/details?id={package_name}",
        "fdroid_url_template": "https://f-droid.org/packages/{package_name}/",
    }
    with patch("crawl._store_url_is_available", return_value=False) as available:
        urls = _build_store_urls("com.example.app", config)

    assert urls["play_store_url"] is not None
    assert urls["fdroid_url"] is None
    available.assert_called_once_with(
        "https://f-droid.org/packages/com.example.app/", config
    )


def test_run_crawl_rejects_an_error_report_path_that_overwrites_catalog(tmp_path):
    output_path = tmp_path / "catalog.json"
    config = {
        "seed_list_path": str(tmp_path / "seed.json"),
        "output_path": str(output_path),
        "error_output_path": str(output_path),
    }

    with patch("crawl._load_seed_list"):
        try:
            run_crawl(config)
        except ValueError as error:
            assert str(error) == "catalog, error, and seed validation paths must differ"
        else:
            raise AssertionError("run_crawl should reject colliding output paths")


def test_run_crawl_rejects_play_404_before_download(tmp_path):
    seed_path = tmp_path / "seed.json"
    output_path = tmp_path / "catalog.json"
    validation_path = tmp_path / "seed-validation.json"
    seed_path.write_text(
        json.dumps(
            [
                {"package_name": "com.invalid.app", "category": "tools"},
                {"package_name": "com.valid.app", "category": "tools"},
            ]
        )
    )
    config = {
        "seed_list_path": str(seed_path),
        "output_path": str(output_path),
        "seed_validation_report_path": str(validation_path),
        "validate_seed_packages": True,
        "play_store_url_template": "https://play.google.com/store/apps/details?id={package_name}",
        "crawler": {"max_workers": 1},
    }
    negative_result = {
        "package_name": "com.valid.app",
        "category": "tools",
        "error": None,
        "satellite_optimized": False,
        "downloaded": False,
        "cached": True,
        "status": "negative",
    }

    with patch(
        "crawl._store_url_status",
        side_effect=[(404, None), (200, None)],
    ), patch("crawl.process_package", return_value=negative_result) as process:
        summary = run_crawl(config)

    process.assert_called_once_with("com.valid.app", "tools", config)
    assert summary["scanned_this_run"] == 1
    assert summary["seed_validation_rejected"] == 1
    assert summary["errors"] == 0
    assert summary["packages_not_found"] == 1
    assert summary["total_failures"] == 1
    validation = json.loads(validation_path.read_text())
    assert validation["accepted_for_crawl"] == 1
    assert validation["rejected"] == 1
    assert validation["entries"] == [
        {
            "package_name": "com.invalid.app",
            "status": "rejected",
            "detail": "Google Play returned HTTP 404",
            "http_status": 404,
            "url": "https://play.google.com/store/apps/details?id=com.invalid.app",
            "category": "tools",
        },
        {
            "package_name": "com.valid.app",
            "status": "valid",
            "http_status": 200,
            "url": "https://play.google.com/store/apps/details?id=com.valid.app",
            "category": "tools",
        },
    ]
    errors = json.loads((tmp_path / "crawl-errors.json").read_text())
    assert errors["total_errors"] == 0
    assert errors["packages_not_found"] == 1
    assert errors["not_found"] == [
        {
            "package_name": "com.invalid.app",
            "error": "package_not_found",
            "detail": "Google Play returned HTTP 404",
        }
    ]
    catalog = json.loads(output_path.read_text())
    assert "com.invalid.app" not in {app["package_name"] for app in catalog["apps"]}
    assert catalog["scanned"]["com.invalid.app"]["last_error"] == "package_not_found"


def test_run_crawl_keeps_unavailable_seed_for_download(tmp_path):
    seed_path = tmp_path / "seed.json"
    output_path = tmp_path / "catalog.json"
    seed_path.write_text(json.dumps([{"package_name": "com.example.app", "category": "tools"}]))
    config = {
        "seed_list_path": str(seed_path),
        "output_path": str(output_path),
        "validate_seed_packages": True,
        "play_store_url_template": "https://play.google.com/store/apps/details?id={package_name}",
        "crawler": {"max_workers": 1},
    }
    result = {
        "package_name": "com.example.app",
        "category": "tools",
        "error": None,
        "satellite_optimized": False,
        "downloaded": False,
        "cached": False,
        "status": "negative",
    }

    with patch("crawl._store_url_status", return_value=(None, "proxy timeout")), patch(
        "crawl.process_package", return_value=result
    ) as process:
        summary = run_crawl(config)

    process.assert_called_once_with("com.example.app", "tools", config)
    assert summary["seed_validation_rejected"] == 0
    validation = json.loads((tmp_path / "seed-validation.json").read_text())
    assert validation["entries"][0]["status"] == "unavailable"
    assert validation["entries"][0]["detail"] == "proxy timeout"


def test_run_crawl_preserves_previous_app_when_worker_fails(tmp_path):
    seed_path = tmp_path / "seed.json"
    output_path = tmp_path / "catalog.json"
    seed_path.write_text(json.dumps([{"package_name": "com.example.app", "category": "tools"}]))
    output_path.write_text(
        json.dumps(
            {
                "apps": [
                    {
                        "package_name": "com.example.app",
                        "app_name": "Example",
                        "satellite_optimized": True,
                    }
                ]
            }
        )
    )
    config = {
        "seed_list_path": str(seed_path),
        "output_path": str(output_path),
        "crawler": {"max_workers": 1},
    }

    with patch("crawl.process_package", side_effect=RuntimeError("temporary failure")):
        summary = run_crawl(config)

    assert summary["errors"] == 1
    catalog = json.loads(output_path.read_text())
    assert catalog["apps"][0]["package_name"] == "com.example.app"
    error_report = json.loads((tmp_path / "crawl-errors.json").read_text())
    assert error_report["errors"] == [
        {
            "package_name": "com.example.app",
            "error": "unhandled_exception",
            "detail": "temporary failure",
        }
    ]


def test_run_crawl_does_not_report_negative_cached_skips(tmp_path):
    seed_path = tmp_path / "seed.json"
    output_path = tmp_path / "catalog.json"
    seed_path.write_text(json.dumps([{"package_name": "com.example.app"}]))

    config = {
        "seed_list_path": str(seed_path),
        "output_path": str(output_path),
        "crawler": {"max_workers": 1},
    }
    result = {
        "package_name": "com.example.app",
        "error": "parse_failed",
        "error_detail": "aapt2 exited with status 1",
        "downloaded": True,
        "cached": False,
    }
    with patch("crawl.process_package", return_value=result):
        summary = run_crawl(config)

    assert summary["cached_skipped"] == 0
    error_report = json.loads((tmp_path / "crawl-errors.json").read_text())
    assert error_report["errors"] == [
        {
            "package_name": "com.example.app",
            "error": "parse_failed",
            "detail": "aapt2 exited with status 1",
        }
    ]


def test_run_crawl_skips_fresh_negative_scan(tmp_path):
    seed_path = tmp_path / "seed.json"
    output_path = tmp_path / "catalog.json"
    seed_path.write_text(json.dumps([{"package_name": "com.example.app", "category": "tools"}]))
    output_path.write_text(
        json.dumps(
            {
                "apps": [],
                "scanned": {
                    "com.example.app": {
                        "package_name": "com.example.app",
                        "category": "tools",
                        "satellite_optimized": False,
                        "status": "negative",
                        "last_scanned": "2099-01-01T00:00:00+00:00",
                    }
                },
            }
        )
    )
    error_report_path = tmp_path / "crawl-errors.json"
    error_report_path.write_text(json.dumps({"total_errors": 1, "errors": ["stale"]}))
    config = {
        "seed_list_path": str(seed_path),
        "output_path": str(output_path),
        "validate_seed_packages": True,
        "play_store_url_template": "https://play.google.com/store/apps/details?id={package_name}",
        "crawler": {"max_workers": 1, "scan_days": 30},
    }

    with patch("crawl._store_url_status") as validate, patch("crawl.process_package") as process:
        summary = run_crawl(config)

    process.assert_not_called()
    validate.assert_not_called()
    assert summary["scanned_this_run"] == 0
    assert summary["scan_skipped"] == 1
    catalog = json.loads(output_path.read_text())
    assert catalog["scanned"]["com.example.app"]["status"] == "negative"
    error_report = json.loads(error_report_path.read_text())
    assert error_report["total_errors"] == 0
    assert error_report["errors"] == []
    validation_report = json.loads((tmp_path / "seed-validation.json").read_text())
    assert validation_report["enabled"] is True
    assert validation_report["total_checked"] == 0

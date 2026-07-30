from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from crawl import _find_cached_apk, _write_catalog, process_package, run_crawl


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
        "last_verified": "2026-07-30",
    }
    negative = {
        "package_name": "com.example.negative",
        "satellite_optimized": False,
        "status": "negative",
    }

    _write_catalog(output_path, [positive, negative], previous, {}, {"com.example.previous"})

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
        "crawl.download", return_value=downloaded_apk
    ), patch("crawl.get_app_info", return_value=None):
        result = process_package("com.example.app", "tools", config)

    assert result["status"] == "positive"
    assert result["downloaded"] is True


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
        "downloaded": True,
        "cached": False,
    }
    with patch("crawl.process_package", return_value=result):
        summary = run_crawl(config)

    assert summary["cached_skipped"] == 0

# Android Satellite Apps

Python crawler that downloads Android APKs, checks their manifests for
`android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED`, and writes a catalog of
matching apps.

The crawler currently covers the U1-U4 pipeline. The Astro site is not yet
implemented.

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- A working Mullvad connection exposing SOCKS5 at `10.64.0.1:1080`

## Setup

From the repository root:

```bash
uv sync
```

Run the test suite:

```bash
uv run pytest -q
```

## Verify Mullvad

The crawler uses `socks5h`, so DNS resolution also goes through Mullvad:

```bash
uv run python -c "import requests; p='socks5h://10.64.0.1:1080'; r=requests.get('https://am.i.mullvad.net/connected', proxies={'http':p,'https':p}, timeout=15); print(r.text)"
```

The response should state that you are connected to Mullvad and show a Mullvad
exit IP.

## Run The Full Crawl

```bash
uv run python crawler/crawl.py
```

The default configuration is `crawler/config.yaml`. The crawl uses the
configured Mullvad proxy, five workers, quiet dependency logging, and the
500-entry seed list.

Output files:

- `crawler/catalog.json`: confirmed apps and scan state
- `crawler/apk_cache/`: downloaded APKs and bundles
- `crawler/apk_cache/.parser_cache.json`: parser cache

Downloaded APKs and parser caches are ignored by Git.

The command exits with status 1 if one or more packages fail, even though a
partial catalog is still written. Review the summary and the `scanned` state in
`crawler/catalog.json`.

## Run A 10-App Test

Create an isolated seed list and configuration:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
import yaml

packages = [
    "com.google.android.apps.messaging",
    "com.google.android.dialer",
    "com.google.android.gm",
    "com.android.chrome",
    "org.telegram.messenger",
    "com.whatsapp",
    "org.fdroid.fdroid",
    "com.google.android.apps.maps",
    "com.google.android.youtube",
    "com.spotify.music",
]

seed = [{"package_name": package, "category": "test"} for package in packages]
config = yaml.safe_load(Path("crawler/config.yaml").read_text())

Path("/tmp/satellite-test-seed.json").write_text(json.dumps(seed, indent=2))
config["seed_list_path"] = "/tmp/satellite-test-seed.json"
config["output_path"] = "/tmp/satellite-test-catalog.json"
config["apk_cache_dir"] = "/tmp/satellite-test-cache"
Path("/tmp/satellite-test-config.yaml").write_text(yaml.safe_dump(config))
PY

uv run python crawler/crawl.py /tmp/satellite-test-config.yaml
```

Inspect the isolated result:

```bash
uv run python -c "import json; print(json.dumps(json.load(open('/tmp/satellite-test-catalog.json')), indent=2))"
```

`com.google.android.apps.messaging` is a likely positive case. APK versions and
source availability can change, so treat other expected outcomes as test
expectations rather than permanent guarantees.

## Incremental Crawls

Each completed scan is recorded in `catalog.json` under `scanned`:

```json
{
  "com.example.app": {
    "category": "test",
    "satellite_optimized": false,
    "status": "negative",
    "last_scanned": "2026-07-30T12:00:00+00:00"
  }
}
```

Successful positive and negative scans younger than `crawler.scan_days` are
skipped. The default is 30 days:

```yaml
crawler:
  scan_days: 30
```

Failed scans remain eligible for retry. New seed packages are scanned
immediately. A positive app that becomes negative is removed from `apps` while
its negative scan remains in `scanned`.

APK reuse and scan scheduling are separate controls:

- `cache_days`: reuse a downloaded APK for this many days
- `scan_days`: skip a successful manifest scan for this many days

## Store Links

Play Store and F-Droid URLs are checked before they are included in an app
entry. Checks use the configured Mullvad SOCKS5 proxy. Set this only for
offline or mocked tests:

```yaml
validate_store_links: false
```

## Configuration

Important settings are in `crawler/config.yaml`:

```yaml
crawler:
  max_workers: 5
  per_source_timeout: 30
  cache_days: 30
  scan_days: 30

proxy:
  enabled: true
  scheme: socks5h
  host: 10.64.0.1
  port: 1080
```

`source_order` controls the justapk fallback order. `quiet: true` suppresses
third-party progress and debug output while retaining the crawl summary.

## Development

Run all tests and checks with:

```bash
uv run pytest -q
uv run python -m compileall -q crawler
uv lock --check
```

`crawler/requirements.txt` is retained as a legacy pip-compatible dependency
list. `pyproject.toml` and `uv.lock` are the source of truth for `uv` setups.

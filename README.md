# SatReady Apps

**Live site: [satreadyapps.com](https://satreadyapps.com)**

SatReady Apps is a catalog of Android apps whose manifests declare
`android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED`.

This repository contains two parts:

- `crawler/`: downloads APKs, inspects their manifests, and writes the catalog.
- `site/`: a static Astro site that publishes the catalog.

The crawler runs locally. Cloudflare Pages builds and hosts the static site from
the committed catalog.

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Android SDK Build-Tools with `aapt2` on `PATH`
- Mullvad exposing a SOCKS5 proxy at `10.64.0.1:1080`

## Set Up The Crawler

From the repository root:

```bash
uv sync
```

The crawler uses `socks5h`, so DNS resolution also goes through Mullvad. Verify
the connection with:

```bash
uv run python -c "import requests; p='socks5h://10.64.0.1:1080'; r=requests.get('https://am.i.mullvad.net/connected', proxies={'http':p,'https':p}, timeout=15); print(r.text)"
```

The response should confirm the Mullvad connection and show a Mullvad exit IP.

## Run A Crawl

Run the full crawl with the default configuration:

```bash
uv run python crawler/crawl.py
```

The default configuration is [`crawler/config.yaml`](crawler/config.yaml). It
uses the configured Mullvad proxy, five workers, the curated seed list, and
incremental scan scheduling.

The crawl writes:

- `crawler/catalog.json`: confirmed apps and scan state; this is the site's source data.
- `crawler/crawl-errors.json`: per-package failure details.
- `crawler/seed-validation.json`: Google Play preflight results.
- `crawler/apk_cache/`: downloaded APKs and bundles.

Downloaded APKs, parser caches, and error reports are ignored by Git. The
crawler exits with status 1 when one or more packages fail, even though it still
writes a partial catalog. Review the crawl summary and the `scanned` state in
`crawler/catalog.json`.

After a successful crawl, review the catalog and commit the updated
`crawler/catalog.json`. That commit triggers a new site deployment.

Each published app also retains a `first_verified_at` timestamp. This is the
stable addition date used by the site's Recently Added section, `/updates/`
page, and `/feed.xml` RSS feed. The crawler's `new_packages` and
`new_addition` fields continue to describe only the current crawl.

## Crawl Configuration

Important settings are in [`crawler/config.yaml`](crawler/config.yaml):

```yaml
crawler:
  max_workers: 5
  cache_days: 30
  scan_days: 30

proxy:
  enabled: true
  scheme: socks5h
  host: 10.64.0.1
  port: 1080
```

- `cache_days` controls how long a downloaded APK can be reused.
- `scan_days` controls how long a successful manifest scan is considered current.
- Failed scans remain eligible for retry.
- New seed packages are scanned immediately.
- Set `AAPT2_PATH` when `aapt2` is not on `PATH`.
- Set `validate_store_links: false` only for offline or mocked tests.

## Develop The Site

The Astro site lives in `site/`:

```bash
cd site
npm install
npm run dev
```

The site syncs and validates `../crawler/catalog.json` before development and
production builds. To create a production build locally:

```bash
npm run build
```

To preview the production output:

```bash
npm run preview
```

## Development Checks

Run the crawler tests and checks from the repository root:

```bash
uv run pytest -q
uv run python -m compileall -q crawler
uv lock --check
```

Build the site from `site/`:

```bash
npm run build
```

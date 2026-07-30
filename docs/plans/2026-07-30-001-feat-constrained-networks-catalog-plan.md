---
title: Constrained Networks App Catalog
type: feat
status: active
date: 2026-07-30
origin: docs/brainstorms/constrained-networks-catalog-requirements.md
---

# Constrained Networks App Catalog

## Summary

Build a Python-based APK crawler that downloads popular Android apps from third-party sources, inspects their manifests for the constrained-satellite-network flag (`android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED`), and produces a structured JSON catalog. Surface the catalog via an Astro static site with search, RSS, and a community submission form. Start as a local POC; publish via Cloudflare Pages and a GitHub repo.

---

## Problem Frame

There is no public catalog of Android apps that support constrained satellite networks. The manifest flag that opts apps into satellite connectivity is not queryable via any Google API or Play Store search. Users with satellite-capable phones have no way to discover compatible apps. An automated crawling pipeline that checks APK manifests is the most practical discovery mechanism.

---

## Requirements

- R1. Monthly pipeline downloads APKs from multiple public sources with automatic fallback.
- R2. Pipeline checks each APK's manifest for the satellite-optimized meta-data flag.
- R3. Confirmed apps recorded with package name, display name, icon URL, and store links.
- R4. Pipeline detects new additions since previous run and flags them.
- R5. Initial seed list: top 500 apps by Play Store category from public rankings.
- R6. Static website (Astro) displays app listing with search.
- R7. Website shows app name, icon, package name, and store links.
- R8. Website offers RSS/Atom feed for new additions.
- R9. Website includes submission form for nominating apps.

**Origin actors:** A1 (end user), A2 (crawler pipeline), A3 (submitter)

**Origin flows:** F1 (monthly catalog refresh), F2 (user browses catalog), F3 (community submits an app)

---

## Scope Boundaries

- No companion Android app (on-device scanning deferred).
- No Play Store API integration.
- No user accounts, ratings, or reviews.
- No per-app bandwidth or performance data.
- No real-time crawling — monthly updates only.
- Submission form is a nomination queue, not instant verification; verification happens on the next crawl cycle.
- CI/CD automation deferred to post-POC — initial runs are local/manual.

---

## Context & Research

### Relevant Code and Patterns

- Greenfield project — no existing code or conventions to follow.

### External References

- [Android constrained satellite networks docs](https://developer.android.com/develop/connectivity/satellite/constrained-networks)
- [justapk](https://github.com/TheQmaks/justapk) — multi-source APK downloader with auto-fallback (APKPure, F-Droid, APKMirror, Uptodown, APKCombo, APK20)
- [aapt2](https://developer.android.com/studio/command-line/aapt2) — Android Asset Packaging Tool for manifest extraction
- [androguard](https://github.com/androguard/androguard) — Python library for APK analysis (alternative to aapt)
- [Astro](https://astro.build) — static site generator

---

## Key Technical Decisions

- **Python for the crawler:** Both justapk and manifest parsing tooling (aapt, androguard) are Python-native. Minimizes glue code.
- **justapk for APK download:** Covers 6 sources with automatic fallback. Best single library for reliable multi-source crawling.
- **androguard for manifest inspection:** Pure Python, pip-installable, handles XAPK extraction natively. aapt2 is an optional optimization if the Android SDK is available.
- **JSON as the catalog interchange format:** Portable, diffable, directly consumed by Astro. Each crawl generates a single `catalog.json` file.
- **Astro for the site:** Static output means cheap hosting (Cloudflare Pages free tier). Content collections from local JSON provide type-safe data access.
- **Start local, publish later:** All development runs on the local machine. The GitHub repo + Cloudflare Pages deployment is added once the POC is stable.

---

## Open Questions

### Resolved During Planning

- Crawler language: Python.
- APK download library: justapk.
- Hosting: Cloudflare Pages (post-POC).

### Deferred to Implementation

- Exact source for the top-500 seed list (various public rankings available — AppBrain, 42matters, StatCounter).
- Submission form backend mechanism (likely Cloudflare Pages Functions or GitHub Issues API — decide when adding deployment).
- Phase 1 submission form data persistence — console.log/localStorage loses submissions. Should write to a local JSON file or use a lightweight serverless endpoint.
- RSS implementation details (Astro has built-in RSS feed support).

---

## Output Structure

```
android-satellite-apps/
├── crawler/
│   ├── requirements.txt
│   ├── config.yaml              # seed list path, output paths, interval config
│   ├── seed_list.json           # top 500 package names + metadata
│   ├── crawl.py                 # orchestrator: download → parse → catalog
│   ├── downloader.py            # justapk wrapper
│   ├── parser.py                # aapt2/androguard manifest checker
│   ├── catalog.json             # output: all confirmed satellite-optimized apps
│   ├── apk_cache/               # cached APK downloads (gitignored)
│   └── tests/
│       ├── test_downloader.py
│       └── test_parser.py
├── site/
│   ├── package.json
│   ├── astro.config.mjs
│   ├── src/
│   │   └── data/                # catalog.json sourced as Astro data store
│   │   ├── components/
│   │   ├── layouts/
│   │   └── pages/
│   ├── public/
│   └── dist/                    # build output
└── docs/
    ├── brainstorms/
    │   └── constrained-networks-catalog-requirements.md
    └── plans/
        └── 2026-07-30-001-feat-constrained-networks-catalog-plan.md
```

---

## Implementation Units

### U1. Seed list and data schemas

**Goal:** Create the initial seed list of top Android apps and define the catalog JSON schema.

**Requirements:** R5

**Dependencies:** None

**Files:**
- Create: `crawler/seed_list.json`
- Create: `crawler/config.yaml`
- Create: `crawler/requirements.txt`

**Approach:**
- Research and compile a JSON list of the top ~500 Android package names from public rankings (AppBrain top apps, 42matters, or manual category sampling from Google Play).
- Format: `[{"package_name": "com.example.app", "source": "appbrain", "category": "communication"}]`
  - Define the catalog output schema in code comments/documentation in `config.yaml`:
  - `package_name`, `app_name`, `icon_url`, `play_store_url`, `fdroid_url`, `last_verified`, `category`
- Pin Python dependencies: `pyyaml`, `requests`, plus justapk and androguard (added after U2 confirms approach).

**Test scenarios:**
- The seed list parses correctly as valid JSON.
- All package names match the `com.example.app` pattern.
- No duplicate package names in the list.

**Verification:**
- `uv run python -c "import json; data=json.load(open('crawler/seed_list.json')); print(len(data))"` outputs 400-600 entries with no duplicates.

---

### U2. APK downloader module

**Goal:** A Python module that downloads the latest APK for a given package name from available public sources, using automatic fallback.

**Requirements:** R1

**Dependencies:** U1 (for package name format and config path)

**Files:**
- Create: `crawler/downloader.py`
- Create: `crawler/tests/test_downloader.py` (optional for POC, but structure for it)

**Approach:**
- Wrap justapk's Python API for multi-source downloading.
- Accept a package name and optional output directory.
- Use a SOCKS5 proxy (Mullvad) for all requests to avoid exposing the home IP and mitigate source-level blocking.
- Try sources in order: APKPure → F-Droid → APKMirror → Uptodown → APKCombo. Stop at first success.
- Return path to downloaded APK (or None if all sources fail).
- Timeout per source: 30 seconds. Total timeout: 180 seconds.
- Log failures per source for diagnostics.

**Patterns to follow:**
- justapk Python API examples in its README: `Downloader.download("org.telegram.messenger", output_dir=Path("./apks/"))`

**Test scenarios:**
- **Happy path:** Download a well-known package (e.g., `org.telegram.messenger`) — returns a valid `.apk` file path.
- **Fallback:** Package not on first source — succeeds on second or third source.
- **All sources fail:** Random non-existent package name — returns `None`.
- **Invalid package name:** Empty string or malformed name — returns `None` without crashing.

**Verification:**
- Running `uv run python -c "import sys; sys.path.insert(0, 'crawler'); from downloader import download; path = download('org.telegram.messenger')"` produces a valid `.apk` file.

---

### U3. Manifest parser module

**Goal:** A Python module that extracts and checks AndroidManifest.xml for the `android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED` meta-data flag.

**Requirements:** R2

**Dependencies:** U2 (needs downloaded APK files to parse)

**Files:**
- Create: `crawler/parser.py`
- Create: `crawler/tests/test_parser.py`

**Approach:**
- Extract `AndroidManifest.xml` from APK using androguard's `APK.get_android_manifest_xml()` (primary). Optionally fall back to `aapt2 dump xmltree` if the Android SDK is installed.
- Check for `<meta-data android:name="android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED" android:value="PACKAGE_NAME" />`.
- Return `True`/`False` with the parsed manifest metadata (app name, icon path within APK).
- Handle XAPK files by extracting the base APK first.
- Cache parsed results to avoid re-parsing on re-crawl.

**Test scenarios:**
- **Happy path:** APK with the satellite flag — returns `True` and app name.
- **No flag:** Standard APK without the flag — returns `False`.
- **Invalid APK:** Corrupted file — returns `False` and logs error.
- **XAPK format:** XAPK file containing a base APK — correctly extracts base APK and checks manifest.

**Verification:**
- Manually test against a known app that has the flag (e.g., check if any Google apps like Gmail or Messages have it on Android 16+ devices).
- Unit test with a hand-crafted minimal APK containing the flag.

---

### U4. Crawl orchestrator

**Goal:** The main pipeline script that coordinates download → parse → catalog generation for the entire seed list.

**Requirements:** R1, R2, R3, R4

**Dependencies:** U1, U2, U3

**Files:**
- Create: `crawler/crawl.py`
- Modify: `crawler/config.yaml`
- Create: `crawler/catalog.json`

**Approach:**
- Read seed list and config from `config.yaml`. Use a ThreadPoolExecutor (configurable concurrency in config.yaml, default 5 workers) for parallel per-package processing.
- For each package name:
  1. Check if a recent cached APK exists (skip re-download if < 30 days old).
  2. Download via `downloader.py`.
  3. Parse via `parser.py`.
  4. If satellite-optimized, collect: package name, app name, icon URL (tiered: justapk info API → androguard APK icon extraction → letter-initial fallback), store links.
- Compare results against previous `catalog.json` to identify new additions.
- Add `last_verified` date and a `new_additions` flag list.
- Write `catalog.json`.
- Log summary: total processed, downloaded, sat-optimized found, errors.

**Test scenarios:**
- **Full run:** Process a small seed list of 10 apps — at least one satellite-optimized app found (if any exist).
- **Delta detection:** Second run with the same data — `new_additions` list is empty.
- **Resume:** Run interrupted mid-crawl — re-running skips already-processed apps using cached APKs.

**Verification:**
- Running `uv run python crawler/crawl.py` produces a valid `catalog.json` with the expected structure.
- The output contains no duplicate package names.

---

### U5. Astro site — listing and detail pages

**Goal:** A static website that reads the catalog JSON and renders a browsable, searchable app listing with detail pages.

**Requirements:** R6, R7

**Dependencies:** U4 (needs `catalog.json`)

**Files:**
- Create: `site/package.json`
- Create: `site/astro.config.mjs`
- Create: `site/tsconfig.json`
- Create: `site/src/data/catalog.json` (symlink or copy of crawler/catalog.json)
- Create: `site/src/pages/index.astro`
- Create: `site/src/pages/apps/[package].astro`
- Create: `site/src/layouts/BaseLayout.astro`
- Create: `site/src/components/AppCard.astro`
- Create: `site/src/components/AppGrid.astro`
- Create: `site/src/components/SearchBar.astro`
- Create: `site/src/pages/404.astro`
- Create: `site/src/styles/global.css`
- Create: `site/public/favicon.svg`

**Approach:**
- Scaffold Astro project with TypeScript.
- Source `catalog.json` as an Astro data store via `src/data/catalog.json` (file-based data collection).
- **Home page:** Grid of app cards showing icon, name, package name. Search bar at top filters by name client-side.
- **Detail page:** `/apps/[package]` — shows full info: name, icon, package name, store links, last verified date. If the package doesn't exist, shows "This app is not in the catalog" with a link back to the home page.
- **Custom 404 page:** `src/pages/404.astro` — friendly branded 404 for any invalid route.
- Mobile-responsive layout with minimal CSS (no framework — keep it fast). Breakpoints: 640px (2-column grid), 1024px (3-column grid).
- Icon fallback: letter-initial (first character of app name) in a colored circle. AppCard uses fixed aspect-ratio containers with `object-fit: cover` to prevent layout shift on missing images.
- Accessibility: SearchBar announces result count via `aria-live="polite"`. SubmitForm uses native `<label>` elements and `aria-describedby` for error messages.
- Search implemented client-side with a lightweight approach (plain JS or a tiny library like Fuse.js if fuzzy matching desired).

**Patterns to follow:**
- Astro's [data collections](https://docs.astro.build/en/guides/content-collections/) for type-safe JSON loading.
- Astro's [client-side search](https://docs.astro.build/en/recipes/search/) patterns.

**Test scenarios:**
- **Listing:** Page renders all apps from catalog JSON as a grid.
- **Detail:** Each app name links to a working detail page at `/apps/[package]`.
- **Search:** Typing in the search bar filters displayed apps by name.
- **Empty state:** No apps match search — shows "No apps found" message.
- **Mobile:** Layout stacks vertically on small screens.

**Verification:**
- `npm run build` completes without errors.
- `npm run preview` shows a working site with all catalog apps listed.
- Each detail page loads at `/apps/` URLs.

---

### U6. RSS feed and recent additions

**Goal:** Add an RSS/Atom feed and a "Recently Added" section to the Astro site.

**Requirements:** R8

**Dependencies:** U5 (site structure in place)

**Files:**
- Modify: `site/src/pages/index.astro`
- Create: `site/src/pages/feed.xml.js` (or `.astro`)

**Approach:**
- Astro's built-in RSS feed support: generate a `feed.xml` endpoint at build time.
- Feed includes: app name, package name, and date added for each new app.
- "Recently Added" section on the home page (top 10 most recently verified apps, or apps added in the last 30 days).

**Test scenarios:**
- Feed XML validates as RSS 2.0.
- Feed contains entries for all apps with `last_verified` dates.
- "Recently Added" section shows correct subset of apps.

**Verification:**
- Visiting `/feed.xml` returns valid RSS XML.
- Home page shows a "Recently Added" section.

---

### U7. Community submission form

**Goal:** A simple form on the site where users can submit an app's package name for the catalog.

**Requirements:** R9

**Dependencies:** U5 (site structure in place)

**Files:**
- Create: `site/src/pages/submit.astro`
- Create: `site/src/components/SubmitForm.astro`
- Create: `site/src/pages/api/submit.js` (serverless function — placeholder for now)

**Approach:**
- **Phase 1 (POC):** Static form page that collects package name + optional notes. Form POSTs to a placeholder endpoint. Display a "submission received" message. Submissions are logged to browser console / local storage for now.
- **Phase 2 (post-POC):** Connect to a real backend — Cloudflare Pages Functions (writes to a JSON file or GitHub Issue via API).
- Include client-side validation: package name format (`com.example.app`), required field, spam prevention (honeypot field).

**Test scenarios:**
- **Valid submission:** Enter `com.example.app` → shows success message.
- **Invalid package name:** Enter `not-a-package` → shows validation error.
- **Empty form:** Submit without filling → shows "package name required" error.
- **Form renders:** Page is accessible at `/submit` and renders correctly.

**Verification:**
- `/submit` page loads and the form accepts test input with validation.

---

## System-Wide Impact

- **Interaction graph:** The catalog flows one way: crawl → JSON → static site. No runtime coupling between components.
- **Error propagation:** Crawl failures are per-package and logged. A single failure doesn't halt the pipeline. The static site build fails only if `catalog.json` is missing or malformed.
- **State lifecycle risks:** None significant — the catalog is regenerated monthly from scratch. Previous data is overwritten.
- **Integration coverage:** The crawl output (catalog.json) is the contract between the Python pipeline and the Astro site. Test by checking schema validity.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Third-party APK sources go offline, add blocking, or IP-ban the crawler | justapk's multi-source fallback handles most failures. SOCKS5 proxy (Mullvad) protects the home IP. Log source failures for monitoring. Accept that some apps may be missed. |
| aapt2 not available on all platforms | androguard is the primary parser (pure Python, pip-installable). aapt2 is optional if Android SDK is present. |
| No satellite-optimized apps found in top 500 | Unlikely (Google and partners are shipping satellite-optimized apps). If true, widen the seed list. |
| Play Store link resolution requires scraping | Use a known URL pattern: `https://play.google.com/store/apps/details?id=<package>`. No scraping needed. |
| Icon URL resolution requires scraping | Tiered approach: (1) try justapk's info API for icon URL, (2) extract icon from downloaded APK via androguard, (3) fall back to a letter-initial icon in a colored circle. |

---

## Documentation / Operational Notes

- **Setup:** `uv sync` from the repository root. `npm install` in `site/`.
- **Running:** `uv run python crawler/crawl.py` then `cd site && npm run build`.
- **First crawl:** The top-500 seed list combined with multi-source downloading + manifest parsing will take approximately 4-8 hours sequentially, or ~1 hour with 5-10 parallel workers. U4 includes a ThreadPoolExecutor with configurable concurrency in `config.yaml`.
- **Caching:** Downloaded APKs cached by package name in `crawler/apk_cache/`. Subsequent monthly runs only download apps without cache entries, making them much faster.

---

## Sources & References

- **Origin document:** [docs/brainstorms/constrained-networks-catalog-requirements.md](/docs/brainstorms/constrained-networks-catalog-requirements.md)
- **justapk:** https://github.com/TheQmaks/justapk
- **aapt2 docs:** https://developer.android.com/studio/command-line/aapt2
- **Astro RSS:** https://docs.astro.build/en/guides/rss/
- **Cloudflare Pages:** https://pages.cloudflare.com/

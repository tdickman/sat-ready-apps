---
title: Constrained Networks App Catalog
type: feat
status: active
date: 2026-07-30
origin: docs/brainstorms/constrained-networks-catalog-requirements.md
---

# Constrained Networks App Catalog

## Summary

The Python APK crawler is implemented and produces a structured JSON catalog of apps that declare the constrained-satellite-network flag (`android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED`). This plan covers the remaining Astro static site: searchable listings, RSS, and a community submission form. Start as a local POC; publish via Cloudflare Pages and a GitHub repo later.

---

## Problem Frame

There is no public catalog of Android apps that support constrained satellite networks. The manifest flag that opts apps into satellite connectivity is not queryable via any Google API or Play Store search. Users with satellite-capable phones have no way to discover compatible apps. An automated crawling pipeline that checks APK manifests is the most practical discovery mechanism.

---

## Requirements

- R6. Static website (Astro) displays the app listing.
- R7. Website shows app name, icon, package name, and store links.
- R8. Website supports search by app name.
- R9. Website offers RSS/Atom feed for new additions.
- R10. Website includes a submission form for nominating apps.

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

- The crawler baseline is implemented under `crawler/`; the site is the remaining greenfield component.

### External References

- [Astro](https://astro.build) — static site generator

---

## Key Technical Decisions

- **JSON as the catalog interchange format:** The completed crawler writes `crawler/catalog.json` with `meta`, `apps`, and `scanned` sections. Astro consumes the generated file at build time.
- **Astro for the site:** Static output means cheap hosting (Cloudflare Pages free tier). Content collections from local JSON provide type-safe data access.
- **Start local, publish later:** All development runs on the local machine. The GitHub repo + Cloudflare Pages deployment is added once the POC is stable.

---

## Open Questions

### Deferred to Implementation

- How the site build gets the generated `crawler/catalog.json` (copy, symlink, or a build-time sync step).
- Whether search matches only app names or also package names and categories.
- Whether “recently added” means the latest crawl additions or apps verified in the last 30 days. The current catalog has `meta.new_packages` and per-app `new_addition`, but no durable `date_added` field.
- Submission form backend mechanism (likely Cloudflare Pages Functions or GitHub Issues API — decide when adding deployment).
- RSS format and item URL/date details (Astro has built-in RSS feed support).

---

## Output Structure

```
android-satellite-apps/
├── crawler/catalog.json         # generated input from the completed crawler
├── site/                        # planned Astro output
│   ├── package.json
│   ├── astro.config.mjs
│   ├── src/
│   │   ├── data/                # catalog.json sourced as Astro data store
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

### U1. Astro site — listing and detail pages

**Goal:** A static website that reads the catalog JSON and renders a browsable, searchable app listing with detail pages.

**Requirements:** R6, R7, R8

**Dependencies:** Completed crawler baseline (needs `crawler/catalog.json`)

**Files:**
- Create: `site/package.json`
- Create: `site/astro.config.mjs`
- Create: `site/tsconfig.json`
- Create: `site/src/data/catalog.json` (or implement a documented build-time sync from `crawler/catalog.json`)
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
- Choose and document one build-time sync mechanism from `crawler/catalog.json`, then source the synchronized file as an Astro data store.
- **Home page:** Grid of app cards showing icon, name, package name. Search bar at top filters by name client-side.
- **Detail page:** `/apps/[package]` — shows full info: name, icon, package name, store links, last verified date. If the package doesn't exist, shows "This app is not in the catalog" with a link back to the home page.
- **Custom 404 page:** `src/pages/404.astro` — friendly branded 404 for any invalid route.
- Mobile-responsive layout with minimal CSS (no framework — keep it fast). Breakpoints: 640px (2-column grid), 1024px (3-column grid).
- Icon fallback: letter-initial (first character of app name) in a colored circle. AppCard uses fixed aspect-ratio containers with `object-fit: cover` to prevent layout shift on missing images.
- Accessibility: SearchBar announces result count via `aria-live="polite"`, uses a native label, and supports keyboard interaction.
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

### U2. RSS feed and recent additions

**Goal:** Add an RSS/Atom feed and a "Recently Added" section to the Astro site.

**Requirements:** R9

**Dependencies:** U1 (site structure and catalog sync in place)

**Files:**
- Modify: `site/src/pages/index.astro`
- Create: `site/src/pages/feed.xml.js` (or `.astro`)

**Approach:**
- Astro's built-in RSS feed support: generate a `feed.xml` endpoint at build time.
- Choose RSS 2.0 or Atom, define canonical item URLs, and include app name, package name, and the selected addition date.
- Define one recent-app rule. The current catalog exposes `meta.new_packages` and per-app `new_addition`, but no durable `date_added` field.

**Test scenarios:**
- Feed validates as the selected RSS 2.0 or Atom format.
- Feed contains entries for apps with valid selected addition dates.
- "Recently Added" section shows correct subset of apps.

**Verification:**
- Visiting `/feed.xml` returns valid RSS XML.
- Home page shows a "Recently Added" section.

---

### U3. Community submission form

**Goal:** A simple form on the site where users can submit an app's package name for the catalog.

**Requirements:** R10

**Dependencies:** U1 (site structure in place)

**Files:**
- Create: `site/src/pages/submit.astro`
- Create: `site/src/components/SubmitForm.astro`
- Create: `site/src/pages/api/submit.js` only if a serverless submission backend is selected

**Approach:**
- **Phase 1 (POC):** Static form page that collects package name + optional notes. Choose whether this is a UI-only prototype or connects to a real queue; do not claim a submission was received without durable backend handling.
- **Phase 2 (post-POC):** If deferred, connect to a real backend — Cloudflare Pages Functions (writes to a JSON file or GitHub Issue via API).
- Include client-side validation: package name format (`com.example.app`), required field, spam prevention (honeypot field).

**Test scenarios:**
- **Valid submission:** Enter `com.example.app` → shows the configured success or not-connected state.
- **Invalid package name:** Enter `not-a-package` → shows validation error.
- **Empty form:** Submit without filling → shows "package name required" error.
- **Form renders:** Page is accessible at `/submit` and renders correctly.

**Verification:**
- `/submit` page loads and the form accepts test input with validation.

---

## System-Wide Impact

- **Interaction graph:** The completed crawler produces `crawler/catalog.json`; a build-time sync supplies it to the Astro site. A submission backend, if selected, adds a runtime integration to U3.
- **Error propagation:** Crawler failures are per-package and logged. The site build must fail clearly when the catalog is missing or malformed and render an intentional empty state when it contains no apps.
- **State lifecycle risks:** The crawler preserves scan state and prior positive entries across failures. The site consumes the latest generated snapshot at build time.
- **Integration coverage:** The catalog output is the contract between the Python pipeline and the Astro site. Test schema validity, empty catalogs, and new-addition metadata before building the feed.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Catalog sync creates a stale or missing site copy | Use one documented build-time sync step and fail the build when the source is missing or malformed. |
| Empty catalog or missing addition dates produce a broken feed/site | Add empty-state coverage and define the feed/recent-additions behavior when no additions are available. |
| Static hosting cannot receive submissions | Choose a real serverless/GitHub-backed queue or label the POC as UI-only; do not show false success. |
| Invalid or abusive submissions reach the queue | Validate package names, use a honeypot, and define duplicate/error handling. |

---

## Documentation / Operational Notes

- **Setup:** `uv sync` from the repository root. After U1 creates the site, run `npm install` in `site/`.
- **Running:** The completed crawler runs with `uv run python crawler/crawl.py`. After U1, sync `crawler/catalog.json` into the site and run `npm run build` from `site/`.
- **Catalog input:** The crawler output includes `meta`, `apps`, and `scanned`; site code should consume the `apps` list and the addition metadata in `meta`/each app.
- **Crawler operations:** APK caching, scan-state behavior, proxy requirements, and store-link validation are documented in `README.md` and are outside this remaining site plan.

---

## Sources & References

- **Origin document:** [docs/brainstorms/constrained-networks-catalog-requirements.md](/docs/brainstorms/constrained-networks-catalog-requirements.md)
- **Astro RSS:** https://docs.astro.build/en/guides/rss/
- **Cloudflare Pages:** https://pages.cloudflare.com/

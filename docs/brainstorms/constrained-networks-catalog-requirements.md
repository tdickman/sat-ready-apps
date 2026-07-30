---
date: 2026-07-30
topic: constrained-networks-catalog
---

# Constrained Networks App Catalog

## Summary

A public website cataloging Android apps that have opted into constrained satellite networks (via the `android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED` manifest flag). The catalog is populated by an automated monthly pipeline that downloads APKs from multiple sources, inspects their manifests, and publishes a browsable, searchable static site with app listings and an RSS feed for new additions.

---

## Problem Frame

Android 16+ introduces constrained satellite network support. Apps self-identify as satellite-optimized via a manifest metadata entry and appear in the device settings as "satellite-enabled apps." However, there is no public, browseable catalog of these apps — users with satellite-capable devices have no way to discover which apps work on constrained networks before they need them (e.g., while camping, in flight, or in remote areas). The flag is not queryable via the Play Store search or API, making discovery impossible without device-side inspection.

---

## Actors

- A1. **End user**: A person with a satellite-capable Android phone who wants to find apps that work on constrained networks.
- A2. **Crawler pipeline**: The automated system that downloads APKs, inspects manifests, and updates the catalog data.
- A3. **Submitter**: A developer or community member who nominates an app for inclusion in the catalog.

---

## Key Flows

- F1. **Monthly catalog refresh**
  - **Trigger:** Scheduled cron (monthly)
  - **Actors:** A2
  - **Steps:**
    1. Load the current seed list of package names (including community-submitted ones).
    2. For each package, download the latest APK from an available public source (APKPure, APKMirror, F-Droid, etc.), with automatic fallback between sources.
    3. Extract `AndroidManifest.xml` from the APK.
    4. Check for `<meta-data android:name="android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED">`.
    5. If found, record the app's package name, display name, icon URL, and store links.
    6. Compare against the previous catalog and flag new additions.
    7. Generate the updated catalog dataset and rebuild the static site.
  - **Outcome:** The live catalog is up to date.

- F2. **User browses catalog**
  - **Trigger:** User visits the website
  - **Actors:** A1
  - **Steps:**
    1. User lands on the catalog homepage showing all listed apps.
    2. User can search by app name or filter the list.
    3. User clicks an app entry to see its details (name, icon, package name, store links).
    4. User can subscribe to an RSS feed to be notified of new additions.
  - **Outcome:** User finds apps that work on their satellite connection.

- F3. **Community submits an app**
  - **Trigger:** A developer or user submits an app via the website form
  - **Actors:** A3
  - **Steps:**
    1. Submitter provides the app's package name (required) and optional notes.
    2. The submission is queued for review.
    3. On the next monthly crawl, the submitted package name is added to the seed list.
    4. If the app is confirmed satellite-optimized, it appears in the catalog.
  - **Outcome:** Submitter's nominated app is added to the catalog (or not, based on manifest inspection).

---

## Requirements

**Crawler pipeline**

- R1. The system shall maintain a scheduled pipeline that runs monthly, downloading APKs from multiple public sources (APKPure, APKMirror, F-Droid) with automatic fallback between sources.
- R2. The pipeline shall extract each APK's `AndroidManifest.xml` and check for the `android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED` meta-data element.
- R3. Apps confirmed to have the satellite-optimized flag shall be recorded with their package name, display name, icon URL, and store links (at minimum Google Play Store).
- R4. The pipeline shall detect new additions since the previous run and flag them for the RSS feed and "recently added" section.
- R5. The initial seed list shall consist of the top 500 most popular Android apps by Play Store category, gathered from public rankings.

**Website**

- R6. The catalog shall surface via a statically generated website (built with Astro or similar SSG) deployable to GitHub Pages or equivalent.
- R7. The website shall display each app entry with its name, icon, package name, and links to app stores (Play Store, plus F-Droid or others when available).
- R8. The website shall support search by app name.
- R9. The website shall offer an RSS/Atom feed for new additions to the catalog.
- R10. The website shall include a submission form for nominating apps, collecting at minimum the app's package name.

---

## Success Criteria

- A user with a satellite-capable Android phone can visit the site and find apps that work on constrained networks within two clicks.
- The crawler pipeline runs unattended monthly and correctly identifies satellite-optimized apps without false positives.
- New app additions propagate to the live site and RSS feed within one crawl cycle.

---

## Scope Boundaries

- No companion Android app (on-device scanning is deferred — catalog is built entirely via APK crawling).
- No Play Store API integration (the manifest flag is not exposed via any Google API).
- No user accounts or login system.
- No rating, review, or commenting features.
- No per-app bandwidth or performance data beyond the satellite-optimized binary flag.
- No real-time crawling — updates are monthly.
- The submission form is a nomination queue, not an instant-verification system; verification happens on the next scheduled crawl.

---

## Key Decisions

- **Multi-source APK crawling over Play Store scraping:** The manifest flag is not queryable via Play Store. Crawling APK mirror sites with fallback (justapk / apkscraper) is the most practical automated discovery mechanism.
- **Static site over dynamic backend:** A static site (Astro) is cheaper to host, faster to load, and sufficient for a catalog that changes monthly. No database or server required.
- **Monthly refresh cadence:** Satellite-optimized status is a manifest-level binary flag that rarely changes. Weekly or daily crawls add cost without proportionally more value.

---

## Dependencies / Assumptions

- Third-party APK sources (APKPure, APKMirror, etc.) remain accessible. If a source goes offline or adds blocking (e.g., Cloudflare), the pipeline falls back to remaining sources or that app is skipped until the next cycle.
- The `aapt` tool (or equivalent, e.g., `androguard`) can reliably extract and parse the manifest metadata from downloaded APK/XAPK files.
- The top-500 seed list is obtainable from public rankings (e.g., AppBrain, StatCounter, or Play Store category leaders compiled by third parties).
- Apps on the seed list are available on at least one crawlable source. Some may only be on Google Play with no third-party mirror — those will be missed.

---

## Outstanding Questions

### Resolve Before Planning

- None.

### Deferred to Planning

- [Affects R1][Technical] Which specific APK download library/tool to use — justapk, apkscraper, or a custom multi-source pipeline.
- [Affects R5][Needs research] Source of the top-500 seed list — which public rankings are reliable and machine-readable.
- [Affects R10][Technical] Submission form backend — use a serverless function (e.g., Cloudflare Workers) or GitHub Issues API to capture nominations.
- [Affects R7][Needs research] How to reliably resolve app icon URLs and store links from just a package name (e.g., Play Store icon URL pattern, APKPure metadata).

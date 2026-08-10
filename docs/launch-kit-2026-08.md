# SatReady Apps launch kit — August 2026

## Positioning

**One-line pitch:** SatReady Apps is a searchable catalog of Android apps whose released APKs declare support for constrained satellite networks.

**User promise:** Find potentially useful apps before leaving normal coverage, while clearly separating a manifest declaration from carrier or feature guarantees.

**Proof:** The live catalog currently contains 22 checked apps, package-level pages, verification dates, methodology, developer guidance, an RSS feed, and a nomination path. Android documents the constrained-network declaration and the engineering changes apps should make for limited satellite links.[1]

## Search status

- **Technical SEO:** Complete. All 29 sitemap URLs return HTTP 200 with unique titles, descriptions, canonical URLs, and valid structured data.
- **Discovery:** `robots.txt` points crawlers to `https://satreadyapps.com/sitemap.xml`, which is an accepted Google sitemap-discovery method.[2]
- **IndexNow:** Complete. The verification key is hosted on the production domain, and all 29 sitemap URLs were accepted by both IndexNow and Bing on 2026-08-10.[3]
- **Still needed:** Add the domain to Google Search Console and Bing Webmaster Tools so indexing, queries, errors, and sitemap processing can be monitored.
- **Analytics:** Not installed. Choose a privacy approach before adding third-party tracking.

## Free channel priorities

### 1. Earn links from apps already listed

This is the highest-intent channel. Contact a few listed app teams with a factual heads-up and a correction link. Do not lead with a backlink request.

First targets:

1. **onX** — four products are listed; use its official contact route.[7]
2. **CalTopo** — highly relevant outdoor audience; use its support request route.[6]
3. **AccuWeather, Dialpad, Signal, Discord, and Viber** — contact only through a clearly public developer, press, or support route.
4. **T-Mobile satellite-app team** — introduce the independent manifest catalog as a complementary discovery resource, not an official compatibility list.

### 2. Technical communities

Publish an explainer, not a bare link. Before posting, re-check each community's current self-promotion rules.

- Hacker News — `Show HN`
- Reddit — `r/androiddev`, `r/Android`, `r/androidapps`, `r/tmobile`, and `r/Starlink`
- Android developer Discord/Slack groups where Tom is already a participant
- GitHub discussions or issue threads only when the catalog directly answers an existing question

### 3. Android and connectivity press

Pitch the data/method angle: the Play Store does not expose this manifest field as a searchable catalog, so SatReady Apps checks released APKs. Android Authority publicly accepts news tips through its contact route.[5]

Initial publications:

- Android Authority
- Android Police
- 9to5Google
- How-To Geek
- GSMArena
- RCR Wireless News
- Outdoor and satellite-connectivity newsletters

### 4. Launch platforms

Product Hunt is free and allows makers to submit their own products.[4] It is secondary to niche outreach because its audience is broader and less intent-driven.

Lower priority:

- Product Hunt
- Indie Hackers product/showcase posts
- Hacker News `Show HN`
- General startup directories only when submission is free and no reciprocal-link requirement exists

Do not use AlternativeTo unless SatReady Apps gains a genuine software-alternative use case; it is currently a reference catalog, not a replacement for another app.

## Ready-to-post drafts

### Show HN / technical Reddit

**Title:** I built a searchable catalog of Android apps that declare satellite-data support

**Body:**

> Android has a manifest property for apps designed to work on constrained satellite networks, but it is not easy to search in the Play Store. I built SatReady Apps to inspect released APK manifests and publish the matching package names, verification dates, and official store links.
>
> The catalog currently has 22 apps: https://satreadyapps.com
>
> Methodology: https://satreadyapps.com/methodology/
>
> A listing confirms the manifest declaration—not that every feature works with every phone, carrier, or satellite service. Corrections and app suggestions are welcome.

### r/tmobile / r/Starlink

**Title:** I made a searchable list of Android apps that declare limited satellite-data support

**Body:**

> I wanted a way to find Android apps that have the platform's satellite-data optimization declaration, without relying only on marketing lists. SatReady Apps checks released APK manifests and publishes the package name and verification date:
>
> https://satreadyapps.com
>
> This is not an official T-Mobile or Starlink compatibility list. Your phone, plan, provider, and the specific app feature still matter. I would appreciate corrections or suggestions for packages to check.

### Press tip

**Subject:** Searchable catalog finds Android's hidden satellite-ready app signal

> Hi,
>
> I built SatReady Apps, a public catalog that checks released Android APK manifests for `android.telephony.PROPERTY_SATELLITE_DATA_OPTIMIZED`.
>
> The signal is documented by Android but is not exposed as a normal Play Store search filter. The catalog currently publishes 22 matching apps with package names, verification dates, store links, and a methodology explaining the limitations.
>
> Catalog: https://satreadyapps.com
> Methodology: https://satreadyapps.com/methodology/
> Source: https://github.com/tdickman/sat-ready-apps
>
> It is an independent technical catalog, not a carrier compatibility list or a guarantee that every feature works over satellite.

### Listed-app outreach

**Subject:** SatReady Apps listing for `<App Name>`

> Hi,
>
> I maintain SatReady Apps, an independent public catalog of Android apps whose released APK manifests declare support for constrained satellite networks.
>
> We found `<App Name>` (`<package>`) and recorded it here:
> `<detail URL>`
>
> The listing was checked on `<date>`. It confirms the manifest declaration, not bandwidth, carrier support, or every app feature. If anything is stale or should be corrected, please let me know or open an issue:
> https://github.com/tdickman/sat-ready-apps/issues
>
> Thanks,
> Tom

### Product Hunt

- **Name:** SatReady Apps
- **Tagline:** Find Android apps built for constrained satellite networks
- **Short description:** Search manifest-verified Android apps that declare support for limited satellite data. See package names, verification dates, official store links, methodology, and recently added apps.
- **Primary link:** `https://satreadyapps.com/?utm_source=producthunt&utm_medium=launch&utm_campaign=launch_2026_08`

## UTM convention

Use only on outbound promotional links:

`?utm_source=<channel>&utm_medium=<post|email|directory>&utm_campaign=launch_2026_08`

Examples:

- `utm_source=reddit&utm_medium=post&utm_campaign=launch_2026_08`
- `utm_source=hackernews&utm_medium=post&utm_campaign=launch_2026_08`
- `utm_source=androidauthority&utm_medium=email&utm_campaign=launch_2026_08`

## Approval queue

External publishing remains a deliberate action because it represents Tom publicly or contacts third parties.

1. Approve one technical-community post.
2. Approve the press-tip email and recipient list.
3. Approve the first two listed-app messages (onX and CalTopo).
4. Decide whether to launch on Product Hunt.
5. Decide whether privacy-conscious aggregate analytics should be enabled.

## Sources

[1] https://developer.android.com/develop/connectivity/satellite/constrained-networks — Develop for constrained satellite networks
[2] https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap — Build and submit a sitemap
[3] https://www.bing.com/indexnow/getstarted — IndexNow get started
[4] https://www.producthunt.com/launch/preparing-for-launch — Prepare for your Product Hunt launch
[5] https://www.androidauthority.com/contact — Android Authority contact
[6] https://help.caltopo.com/hc/en-us/requests/new — CalTopo support request
[7] https://www.onxmaps.com/contact — onX contact

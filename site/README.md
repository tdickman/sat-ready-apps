# SatReady Apps

The Astro site for [satreadyapps.com](https://satreadyapps.com) is a static catalog generated from `../crawler/catalog.json`.

`npm run sync-catalog` validates the crawler output and copies it into
`src/data/catalog.json`, which is the file Astro imports at build time. Both
`npm run dev` and `npm run build` run this sync first, so the crawler output is
the single source of truth and a missing or malformed catalog fails clearly.

The site exposes the latest additions at `/updates/` and as an RSS feed at
`/feed.xml`. Both use each app's durable `first_verified_at` timestamp from
the crawler catalog.

## Commands

```bash
npm install
npm run dev
npm run build
npm run preview
```

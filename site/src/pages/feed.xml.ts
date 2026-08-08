import type { APIRoute } from "astro";
import { getRecentApps, meta, parseCatalogDate } from "../lib/catalog";

const escapeXml = (value: string) => value
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&apos;");

const formatRssDate = (value?: string) => {
  const date = parseCatalogDate(value);
  return date ? date.toUTCString() : null;
};

export const GET: APIRoute = ({ site }) => {
  const siteUrl = new URL("/", site ?? "https://satreadyapps.com");
  const generatedDate = formatRssDate(typeof meta?.generated_at === "string" ? meta.generated_at : undefined);
  const items = getRecentApps().map((app) => {
    const detailUrl = new URL(`/apps/${encodeURIComponent(app.package_name)}/`, siteUrl).href;
    const addedDate = formatRssDate(app.first_verified_at)!;
    const description = `${app.app_name} was added to SatReady Apps after its Android manifest was checked for the limited-satellite-data setting.`;

    return [
      "    <item>",
      `      <title>${escapeXml(app.app_name)} added to SatReady Apps</title>`,
      `      <description>${escapeXml(description)}</description>`,
      `      <link>${escapeXml(detailUrl)}</link>`,
      `      <guid isPermaLink="true">${escapeXml(detailUrl)}</guid>`,
      `      <pubDate>${escapeXml(addedDate)}</pubDate>`,
      "    </item>",
    ].join("\n");
  }).join("\n");

  const channelUrl = new URL("/updates/", siteUrl).href;
  const body = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0">',
    "  <channel>",
    "    <title>SatReady Apps updates</title>",
    "    <description>New Android apps added to the SatReady Apps catalog.</description>",
    `    <link>${escapeXml(channelUrl)}</link>`,
    ...(generatedDate ? [`    <lastBuildDate>${escapeXml(generatedDate)}</lastBuildDate>`] : []),
    items,
    "  </channel>",
    "</rss>",
  ].join("\n");

  return new Response(body, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
    },
  });
};

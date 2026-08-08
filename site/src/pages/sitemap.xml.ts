import type { APIRoute } from "astro";
import { apps, meta } from "../lib/catalog";

const escapeXml = (value: string) => value
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&apos;");

export const GET: APIRoute = ({ site }) => {
  const siteUrl = new URL("/", site ?? "https://satreadyapps.com");
  const generatedAt = typeof meta?.generated_at === "string" ? meta.generated_at.slice(0, 10) : null;
  const urls = [
    { loc: siteUrl.href, lastmod: generatedAt },
    ...["supported-phones", "developers", "submit"].map((page) => ({
      loc: new URL(`/${page}/`, siteUrl).href,
      lastmod: generatedAt,
    })),
    ...apps.map((app) => ({
      loc: new URL(`/apps/${encodeURIComponent(app.package_name)}/`, siteUrl).href,
      lastmod: app.last_verified || generatedAt,
    })),
  ];
  const entries = urls.map(({ loc, lastmod }) => [
    "  <url>",
    `    <loc>${escapeXml(loc)}</loc>`,
    ...(lastmod ? [`    <lastmod>${escapeXml(lastmod)}</lastmod>`] : []),
    "  </url>",
  ].join("\n")).join("\n");
  const body = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    entries,
    "</urlset>",
  ].join("\n");

  return new Response(body, {
    headers: { "Content-Type": "application/xml; charset=utf-8" },
  });
};

import catalogData from "../data/catalog.json";

export interface CatalogApp {
  package_name: string;
  app_name: string;
  first_verified_at: string;
  icon_url?: string;
  play_store_url?: string;
  fdroid_url?: string;
  last_verified?: string;
  category?: string;
  new_addition?: boolean;
}

function isCatalogApp(value: unknown): value is CatalogApp {
  if (!value || typeof value !== "object") return false;

  const app = value as Record<string, unknown>;
  return typeof app.package_name === "string" && app.package_name.trim() !== ""
    && typeof app.app_name === "string" && app.app_name.trim() !== ""
    && typeof app.first_verified_at === "string" && app.first_verified_at.trim() !== ""
    && !Number.isNaN(Date.parse(app.first_verified_at));
}

if (!Array.isArray(catalogData.apps) || !catalogData.apps.every(isCatalogApp)) {
  throw new Error("Catalog must contain an apps array with valid package_name, app_name, and first_verified_at fields");
}

export const apps = catalogData.apps;
export const meta = catalogData.meta;

export function parseCatalogDate(value?: string): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date;
}

export function formatCatalogDate(value?: string, long = false): string | null {
  const date = parseCatalogDate(value);
  if (!date) return null;

  return date.toLocaleDateString("en", {
    month: long ? "long" : "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function getRecentApps(limit = apps.length): CatalogApp[] {
  return [...apps]
    .filter((app) => parseCatalogDate(app.first_verified_at))
    .sort((left, right) => {
      const leftDate = parseCatalogDate(left.first_verified_at)?.valueOf() ?? 0;
      const rightDate = parseCatalogDate(right.first_verified_at)?.valueOf() ?? 0;
      return rightDate - leftDate || left.app_name.localeCompare(right.app_name);
    })
    .slice(0, limit);
}

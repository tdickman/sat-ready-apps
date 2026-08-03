import catalogData from "../data/catalog.json";

export interface CatalogApp {
  package_name: string;
  app_name: string;
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
    && typeof app.app_name === "string" && app.app_name.trim() !== "";
}

if (!Array.isArray(catalogData.apps) || !catalogData.apps.every(isCatalogApp)) {
  throw new Error("Catalog must contain an apps array with valid package_name and app_name fields");
}

export const apps = catalogData.apps;
export const meta = catalogData.meta;

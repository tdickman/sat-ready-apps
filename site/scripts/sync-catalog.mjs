import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(siteRoot, "..", "crawler", "catalog.json");
const destinationPath = resolve(siteRoot, "src", "data", "catalog.json");

let catalog;
try {
  catalog = JSON.parse(await readFile(sourcePath, "utf8"));
} catch (error) {
  throw new Error(`Unable to read ${sourcePath}: ${error.message}`);
}

if (!catalog || typeof catalog !== "object" || !Array.isArray(catalog.apps)) {
  throw new Error(`${sourcePath} must contain a JSON object with an apps array`);
}

const packageNamePattern = /^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$/;
const packageNames = new Set();
for (const [index, app] of catalog.apps.entries()) {
  if (!app || typeof app !== "object"
    || typeof app.package_name !== "string" || !packageNamePattern.test(app.package_name)
    || typeof app.app_name !== "string" || app.app_name.trim() === ""
    || typeof app.last_verified !== "string" || app.last_verified.trim() === "") {
    throw new Error(`${sourcePath} contains an invalid app at index ${index}`);
  }

  if (packageNames.has(app.package_name)) {
    throw new Error(`${sourcePath} contains duplicate package ${app.package_name}`);
  }
  packageNames.add(app.package_name);

  for (const field of ["icon_url", "play_store_url", "fdroid_url", "category"]) {
    if (field in app && app[field] !== undefined && app[field] !== null && typeof app[field] !== "string") {
      throw new Error(`${sourcePath} contains an invalid ${field} at index ${index}`);
    }
  }
}

const normalized = {
  ...catalog,
  apps: catalog.apps.map((app) => {
    const entry = { ...app };
    for (const field of ["icon_url", "play_store_url", "fdroid_url", "category", "last_verified"]) {
      if (entry[field] == null) {
        delete entry[field];
      }
    }
    return entry;
  }),
};

await mkdir(dirname(destinationPath), { recursive: true });
await writeFile(destinationPath, JSON.stringify(normalized, null, 2));
console.log(`Synced ${catalog.apps.length} apps from ${sourcePath}`);

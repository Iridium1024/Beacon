import { rmSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
for (const name of ["lib", "dist"]) {
  rmSync(resolve(root, name), { recursive: true, force: true });
}


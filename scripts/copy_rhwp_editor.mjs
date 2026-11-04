import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const sourceRoot = join(projectRoot, "node_modules", "@rhwp", "editor");
const targetRoot = join(projectRoot, "static", "vendor", "rhwp-editor");

await mkdir(targetRoot, { recursive: true });
for (const filename of ["index.js", "transport.js", "index.d.ts", "README.md", "package.json"]) {
  await copyFile(join(sourceRoot, filename), join(targetRoot, filename));
}

process.stdout.write(`Copied @rhwp/editor browser files to ${targetRoot}\n`);

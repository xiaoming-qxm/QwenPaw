import { cp, mkdir, rm, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const consoleDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(consoleDir, "..");

const sourceDir = path.resolve(
  process.env.QWENPAW_CONSOLE_DIST_DIR || path.join(consoleDir, "dist"),
);
const targetDir = path.resolve(
  process.env.QWENPAW_BACKEND_CONSOLE_DIR ||
    path.join(repoRoot, "src", "qwenpaw", "console"),
);

async function assertDirectory(dir, label) {
  try {
    const details = await stat(dir);
    if (!details.isDirectory()) {
      throw new Error(`${label} is not a directory: ${dir}`);
    }
  } catch (error) {
    if (error && error.code === "ENOENT") {
      throw new Error(`${label} does not exist: ${dir}`);
    }
    throw error;
  }
}

async function assertBuiltConsole(dir) {
  await assertDirectory(dir, "console dist");
  try {
    const index = await stat(path.join(dir, "index.html"));
    if (!index.isFile()) {
      throw new Error(`console dist index.html is not a file: ${dir}`);
    }
  } catch (error) {
    if (error && error.code === "ENOENT") {
      throw new Error(
        `console dist is missing index.html; run vite build first: ${dir}`,
      );
    }
    throw error;
  }
}

if (sourceDir === targetDir) {
  throw new Error(`refusing to sync console static directory onto itself`);
}

await assertBuiltConsole(sourceDir);
await mkdir(path.dirname(targetDir), { recursive: true });
await rm(targetDir, { recursive: true, force: true });
await cp(sourceDir, targetDir, { recursive: true });

console.log(`[sync-backend-static] ${sourceDir} -> ${targetDir}`);

import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

const root = path.resolve(here, "../..");
const python = process.env.PYTHON ?? path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

// Boots a real stack (API + built dashboard + CPU worker) in a temp dir. Build the dashboard first (npm run build).
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8130", trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  webServer: {
    command: `"${python}" "${path.join(root, "tests/e2e/stack.py")}" --port 8130 --engine ${process.env.E2E_ENGINE ?? "auto"}`,
    url: "http://127.0.0.1:8130/api/v1/health/ready",
    timeout: 90_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
});

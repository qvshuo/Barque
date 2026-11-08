import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";
const python = process.env.BARQUE_TEST_PYTHON ? resolve(process.env.BARQUE_TEST_PYTHON) : "python3";
const shellQuote = (value: string) => "'" + value.replaceAll("'", "'\\''") + "'";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: process.env.BARQUE_TEST_URL || "http://127.0.0.1:18083",
    trace: "retain-on-failure",
  },
  webServer: process.env.BARQUE_TEST_URL
    ? undefined
    : {
        command: `cd .. && ${shellQuote(python)} -m tests.serve_frontend`,
        url: "http://127.0.0.1:18083/api/auth/session",
        reuseExistingServer: false,
      },
});

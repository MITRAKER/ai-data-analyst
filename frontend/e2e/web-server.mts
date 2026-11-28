/**
 * Start the built web UI for the browser tests, the way the Docker image runs
 * it: Next.js's standalone server (see `output` in next.config.ts), with the
 * static files copied next to it, as frontend/Dockerfile does.
 *
 * The server reads PORT, HOSTNAME and BACKEND_URL from the environment.
 */
import { cpSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
require("../.next/standalone/server.js");

// GET /api/health -> {"status": "ok"} while the web UI's server is running.
// Docker's health check uses it. It does not call the Python API.

export function GET(): Response {
  return Response.json({ status: "ok" });
}

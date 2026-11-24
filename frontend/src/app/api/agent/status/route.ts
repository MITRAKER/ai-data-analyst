// GET /api/agent/status -> the API's GET /agent/status (can the agent answer questions?)

import { forward } from "@/lib/backend";

export function GET(request: Request): Promise<Response> {
  return forward("/agent/status", { signal: request.signal });
}

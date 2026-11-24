// GET /api/agent/status -> the API's GET /agent/status (can the agent answer questions?)

import { forward } from "@/lib/backend";
import { checkRead } from "@/lib/guard";

export async function GET(request: Request): Promise<Response> {
  return checkRead(request) ?? (await forward("/agent/status", { signal: request.signal }));
}

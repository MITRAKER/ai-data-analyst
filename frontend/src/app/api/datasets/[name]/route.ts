// GET /api/datasets/{name} -> the API's GET /datasets/{name} (columns, row count, first rows)

import { forward } from "@/lib/backend";

export async function GET(
  request: Request,
  context: RouteContext<"/api/datasets/[name]">,
): Promise<Response> {
  const { name } = await context.params;
  return forward(`/datasets/${encodeURIComponent(name)}`, { signal: request.signal });
}

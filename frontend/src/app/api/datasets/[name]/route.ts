// GET /api/datasets/{name} -> the API's GET /datasets/{name} (columns, row count, first rows)

import { errorResponse, forward } from "@/lib/backend";

export async function GET(
  request: Request,
  context: RouteContext<"/api/datasets/[name]">,
): Promise<Response> {
  const { name } = await context.params;
  // In a URL, "." means "this folder" and ".." "the folder above", so
  // /datasets/.. would be the API's root. No dataset has either name.
  if (name === "." || name === "..") {
    return errorResponse(404, `Unknown dataset: ${name}`);
  }
  return forward(`/datasets/${encodeURIComponent(name)}`, { signal: request.signal });
}

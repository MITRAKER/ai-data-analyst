// GET  /api/datasets -> the API's GET /datasets  (the names of all datasets)
// POST /api/datasets -> the API's POST /datasets (upload a CSV file)

import { MAX_UPLOAD_BYTES } from "@/lib/api";
import { checkLength, forward } from "@/lib/backend";
import { checkRead, checkWrite } from "@/lib/guard";

/** The CSV file, plus room for the form fields around it. */
const MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024;

export async function GET(request: Request): Promise<Response> {
  return checkRead(request) ?? (await forward("/datasets", { signal: request.signal }));
}

export async function POST(request: Request): Promise<Response> {
  // Refuse a file that is too large before forwarding a single byte of it.
  const refused =
    checkWrite(request) ??
    checkLength(request, MAX_UPLOAD_REQUEST_BYTES, "The file is larger than 50 MB.");
  if (refused) {
    return refused;
  }
  // Forward the upload as a stream, without keeping the whole file in memory.
  // fetch() needs `duplex: "half"` for a stream body; TypeScript's list of
  // fetch options doesn't include it yet, hence the wider type.
  const init: RequestInit & { duplex: "half" } = {
    method: "POST",
    headers: { "Content-Type": request.headers.get("content-type") ?? "" },
    body: request.body,
    duplex: "half",
    signal: request.signal,
  };
  return forward("/datasets", init);
}

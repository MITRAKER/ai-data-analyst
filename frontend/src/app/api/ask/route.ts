// POST /api/ask -> the API's POST /ask/stream (the agent's steps, as Server-Sent Events)

import { checkLength, errorResponse, forward } from "@/lib/backend";
import { checkJson, checkWrite } from "@/lib/guard";

/** A question of at most 2,000 characters, as JSON, fits easily. */
const MAX_QUESTION_REQUEST_BYTES = 64 * 1024;

export async function POST(request: Request): Promise<Response> {
  const refused =
    checkWrite(request) ??
    checkJson(request) ??
    checkLength(request, MAX_QUESTION_REQUEST_BYTES, "The question is too long.");
  if (refused) {
    return refused;
  }
  const upstream = await forward("/ask/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    // When the user presses Stop, or closes the page, the browser cancels its
    // request. Passing the signal on cancels ours too, and the API then stops
    // the agent, so it doesn't spend API credits on an answer nobody reads.
    signal: request.signal,
  });
  if (!upstream.ok) {
    return upstream;
  }
  if (upstream.body === null) {
    return errorResponse(502, "The analysis server sent an empty answer.");
  }
  // "no-transform" stops any compression along the way, which would hold the
  // events back until it had collected enough of them.
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}

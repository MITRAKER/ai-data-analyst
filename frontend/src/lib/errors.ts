import { ApiError } from "@/lib/api";
import { StreamError } from "@/lib/sse";

/** A message for the user about something that went wrong. */
export function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof StreamError) {
    return error.message;
  }
  if (error instanceof TypeError) {
    // fetch() rejects with a TypeError when there is no connection at all.
    return "The web server can't be reached. Check your connection and try again.";
  }
  if (error instanceof SyntaxError) {
    return "The server sent data that could not be read.";
  }
  return "Something went wrong. Please try again.";
}

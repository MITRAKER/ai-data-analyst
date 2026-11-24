import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { messageOf } from "@/lib/errors";
import { StreamError } from "@/lib/sse";

describe("messageOf", () => {
  it("passes on our own messages", () => {
    expect(messageOf(new ApiError("Not found.", 404))).toBe("Not found.");
    expect(messageOf(new StreamError("Too large."))).toBe("Too large.");
  });

  it("explains a lost connection and unreadable data", () => {
    expect(messageOf(new TypeError("Failed to fetch"))).toContain("can't be reached");
    expect(messageOf(new SyntaxError("Unexpected token"))).toContain("could not be read");
  });

  it("never shows the details of other errors", () => {
    expect(messageOf(new Error("internal detail"))).toBe("Something went wrong. Please try again.");
    expect(messageOf("a string")).toBe("Something went wrong. Please try again.");
  });
});

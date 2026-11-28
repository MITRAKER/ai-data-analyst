// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { allowedHosts, checkHost, checkJson, checkSameOrigin, hostName } from "@/lib/guard";

function request(headers: Record<string, string>) {
  return new Request("http://localhost:3000/api/ask", { method: "POST", headers });
}

describe("hostName", () => {
  it("takes the name out of a Host header, without the port", () => {
    expect(hostName("localhost:3000")).toBe("localhost");
    expect(hostName("LocalHost")).toBe("localhost");
    expect(hostName("127.0.0.1:3000")).toBe("127.0.0.1");
    expect(hostName("[::1]:3000")).toBe("[::1]");
    expect(hostName("analyst.example")).toBe("analyst.example");
  });

  it("refuses anything that isn't a plain host name", () => {
    for (const host of ["", ":3000", "user@localhost", "localhost/x", "local host", "::1"]) {
      expect(hostName(host)).toBeNull();
    }
    expect(hostName("localhost:123456")).toBeNull(); // a port has at most 5 digits
  });
});

describe("allowedHosts", () => {
  it("is this computer's names, and the ones in ALLOWED_HOSTS", () => {
    expect(allowedHosts("")).toEqual(new Set(["localhost", "127.0.0.1", "[::1]"]));
    expect(allowedHosts(" Analyst.Example ,,other.example ")).toEqual(
      new Set(["localhost", "127.0.0.1", "[::1]", "analyst.example", "other.example"]),
    );
  });

  it("reads ALLOWED_HOSTS from the environment", async () => {
    const named = request({ host: "analyst.example:3000" });
    expect(checkHost(named)?.status).toBe(421);
    vi.stubEnv("ALLOWED_HOSTS", "analyst.example");
    expect(checkHost(named)).toBeNull();
    // Another name is still refused, with the setting to change.
    const response = checkHost(request({ host: "evil.example" }));
    expect(response?.status).toBe(421);
    expect(await response?.json()).toEqual({
      detail:
        "This server only answers to localhost. To use another name, add it to ALLOWED_HOSTS.",
    });
  });
});

describe("checkSameOrigin", () => {
  it("lets the app's own page through, and tools that send no Origin", () => {
    const page = { host: "localhost:3000", origin: "http://localhost:3000" };
    expect(checkSameOrigin(request({ ...page, "sec-fetch-site": "same-origin" }))).toBeNull();
    expect(checkSameOrigin(request({ host: "localhost:3000" }))).toBeNull();
  });

  it("refuses an Origin that names another host, or can't be read", () => {
    for (const origin of ["http://localhost:5173", "http://127.0.0.1:3000", "null", "x"]) {
      const response = checkSameOrigin(request({ host: "localhost:3000", origin }));
      expect(response?.status).toBe(403);
    }
  });

  it("refuses every Sec-Fetch-Site except same-origin", () => {
    for (const site of ["cross-site", "same-site", "none"]) {
      const response = checkSameOrigin(request({ host: "localhost:3000", "sec-fetch-site": site }));
      expect(response?.status).toBe(403);
    }
  });
});

describe("checkJson", () => {
  it("accepts JSON, with or without a charset", () => {
    for (const type of [
      "application/json",
      "Application/JSON",
      "application/json; charset=utf-8",
    ]) {
      expect(checkJson(request({ "content-type": type }))).toBeNull();
    }
  });

  it("refuses other types, and a body with no type", () => {
    for (const type of ["text/plain", "application/x-www-form-urlencoded", "application/jsonx"]) {
      expect(checkJson(request({ "content-type": type }))?.status).toBe(415);
    }
    expect(checkJson(request({}))?.status).toBe(415);
  });
});

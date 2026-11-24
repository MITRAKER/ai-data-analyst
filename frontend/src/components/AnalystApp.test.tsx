import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Plotly from "plotly.js-cartesian-dist-min";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AnalystApp } from "@/components/AnalystApp";
import { SUGGESTIONS } from "@/components/ConversationView";
import { json, openStream, RUN, sse, sseResponse } from "@/test/fakes";

vi.mock("plotly.js-cartesian-dist-min", () => ({
  default: { react: vi.fn(() => Promise.resolve()), purge: vi.fn() },
}));

type Handler = (init?: RequestInit) => Response | Promise<Response>;

const READY = { ready: true, detail: "" };
const INFO = {
  name: "sales",
  row_count: 2000,
  columns: [
    { name: "region", type: "VARCHAR" },
    { name: "order_date", type: "TIMESTAMP" },
  ],
  sample: [["West", "2025-01-01T00:00:00.000"]],
};

/** A fake server: "METHOD /path" -> response. */
function serve(routes: Record<string, Handler>) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const handler = routes[key];
    if (handler === undefined) {
      throw new Error(`unexpected request: ${key}`);
    }
    return handler(init);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function withData(extra: Record<string, Handler> = {}) {
  return serve({
    "GET /api/datasets": () => json({ datasets: ["sales"] }),
    "GET /api/agent/status": () => json(READY),
    ...extra,
  });
}

/** A response whose events the test sends one at a time, with `send`. */
function liveResponse() {
  let send: (event: Record<string, unknown>) => void = () => undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      send = (event) => {
        controller.enqueue(new TextEncoder().encode(sse(event)));
      };
    },
  });
  const response = new Response(body, { headers: { "Content-Type": "text/event-stream" } });
  return {
    response,
    send: (event: Record<string, unknown>) => {
      send(event);
    },
  };
}

/** A response that the test sends later, by calling `answer`. */
function later() {
  const answers: ((response: Response) => void)[] = [];
  return {
    respond: () =>
      new Promise<Response>((resolve) => {
        answers.push(resolve);
      }),
    /** The requests made so far. */
    count: () => answers.length,
    /** Answer request number `index` (0 is the first). */
    answer: async (index: number, response: Response) => {
      await act(async () => {
        answers[index]?.(response);
        // Let the app read the answer and update the page.
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
    },
  };
}

async function ask(question: string) {
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "sales" });
  await user.type(screen.getByRole("textbox", { name: "Your question" }), `${question}{Enter}`);
  return user;
}

describe("AnalystApp", () => {
  it("answers a question, showing each step, the table and the chart", async () => {
    const fetch = withData({ "POST /api/ask": () => sseResponse(...RUN) });
    render(<AnalystApp />);
    await ask("Which region sold most?");

    expect(await screen.findByText("West", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Which region sold most?")).toBeInTheDocument();
    expect(screen.getByText("Show the 3 steps the agent took")).toBeInTheDocument();
    expect(screen.getByText("572569.11")).toBeInTheDocument();
    expect(screen.getByText(/SELECT region, SUM\(revenue\)/)).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Revenue by region" })).toBeInTheDocument();
    await vi.waitFor(() => {
      expect(Plotly.react).toHaveBeenCalled();
    });
    const body = fetch.mock.calls.find(([url]) => url === "/api/ask")?.[1]?.body;
    expect(body).toBe(JSON.stringify({ question: "Which region sold most?" }));
  });

  it("shows the API's error when it refuses a question", async () => {
    withData({ "POST /api/ask": () => json({ detail: "Agent unavailable: no key." }, 503) });
    render(<AnalystApp />);
    await ask("Who sold most?");
    expect(await screen.findByText("Agent unavailable: no key.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeInTheDocument();
  });

  it("shows an error when the answer stops before the end", async () => {
    withData({ "POST /api/ask": () => sseResponse({ type: "note", text: "Thinking it over." }) });
    render(<AnalystApp />);
    await ask("Who sold most?");
    expect(await screen.findByText(/connection closed before the agent finished/)).toBeVisible();
  });

  it("stops a running question, and then answers the next one", async () => {
    const signals: AbortSignal[] = [];
    withData({
      "POST /api/ask": (init) => {
        const signal = init?.signal ?? new AbortController().signal;
        signals.push(signal);
        return signals.length === 1
          ? openStream(signal, { type: "note", text: "Hmm." })
          : sseResponse(...RUN);
      },
    });
    render(<AnalystApp />);
    const user = await ask("Who sold most?");
    await screen.findByText("Hmm.");
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByText(/Stopped/)).toBeInTheDocument();
    expect(signals[0]?.aborted).toBe(true);

    await user.type(screen.getByRole("textbox", { name: "Your question" }), "And now?{Enter}");
    expect(await screen.findByText("West", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText(/Stopped/)).toBeInTheDocument(); // the first answer stays stopped
    expect(signals[1]?.aborted).toBe(false);
  });

  it("follows new steps only while the view is at the bottom", async () => {
    const live = liveResponse();
    withData({ "POST /api/ask": () => live.response });
    render(<AnalystApp />);
    await ask("Who sold most?");
    const list = await screen.findByRole("list", { name: "Questions and answers" });
    const view = list.parentElement?.parentElement;
    if (!view) {
      throw new Error("the scrolling view is missing");
    }
    // jsdom has no layout, so give the view a size: 1000 pixels of content
    // in a 400-pixel-high box.
    Object.defineProperty(view, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(view, "clientHeight", { configurable: true, value: 400 });

    view.scrollTop = 100; // the user scrolls up to read something
    fireEvent.scroll(view);
    live.send({ type: "note", text: "First step." });
    await screen.findByText("First step.");
    expect(view.scrollTop).toBe(100);

    view.scrollTop = 600; // and back down to the bottom
    fireEvent.scroll(view);
    live.send({ type: "note", text: "Second step." });
    await screen.findByText("Second step.");
    expect(view.scrollTop).toBe(1000);
  });

  it("asks a suggested question", async () => {
    const fetch = withData({ "POST /api/ask": () => sseResponse(...RUN) });
    render(<AnalystApp />);
    const user = userEvent.setup();
    const suggestion = await screen.findByRole("button", { name: SUGGESTIONS[0] });
    await vi.waitFor(() => {
      expect(suggestion).toBeEnabled();
    });
    await user.click(suggestion);
    // The suggestions are gone, so the keyboard focus moves to the question box.
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveFocus();
    await screen.findByText("West", { selector: "strong" });
    const body = fetch.mock.calls.find(([url]) => url === "/api/ask")?.[1]?.body;
    expect(body).toBe(JSON.stringify({ question: SUGGESTIONS[0] }));
  });

  it("explains why the agent can't answer yet", async () => {
    serve({
      "GET /api/datasets": () => json({ datasets: ["sales"] }),
      "GET /api/agent/status": () =>
        json({ ready: false, detail: "ANTHROPIC_API_KEY is not set." }),
    });
    render(<AnalystApp />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "The agent can't answer questions yet. ANTHROPIC_API_KEY is not set.",
    );
    expect(screen.getByRole("button", { name: SUGGESTIONS[0] })).toBeDisabled();
  });

  it("says when the server can't be reached", async () => {
    serve({
      "GET /api/datasets": () => json({ detail: "The analysis server is not reachable." }, 502),
      "GET /api/agent/status": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    render(<AnalystApp />);
    expect(await screen.findByRole("status")).toHaveTextContent("can't be reached");
    expect(await screen.findByRole("alert")).toHaveTextContent("not reachable");
    // Nobody knows yet whether there are datasets, so neither the list nor
    // the welcome claims that there are none.
    expect(screen.queryByText("No datasets yet.")).toBeNull();
    expect(screen.queryByText("Loading datasets…")).toBeNull();
    expect(screen.queryByText("Start with some data")).toBeNull();
  });
});

describe("DatasetPanel", () => {
  it("uploads a CSV file and shows its details", async () => {
    let uploaded = false;
    serve({
      "GET /api/datasets": () => json({ datasets: uploaded ? ["sales"] : [] }),
      "GET /api/agent/status": () => json(READY),
      "POST /api/datasets": () => {
        uploaded = true;
        return json(INFO, 201);
      },
    });
    render(<AnalystApp />);
    expect(await screen.findByText("No datasets yet.")).toBeInTheDocument();
    const user = userEvent.setup();
    const file = new File(["region\nWest\n"], "sales.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Upload CSV"), file);

    const details = await screen.findByRole("region", { name: "Details of sales" });
    expect(within(details).getByText("2,000 rows, 2 columns")).toBeInTheDocument();
    expect(within(details).getByText("2025-01-01")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "sales", pressed: true })).toBeVisible();
  });

  it("shows why an upload failed", async () => {
    serve({
      "GET /api/datasets": () => json({ datasets: [] }),
      "GET /api/agent/status": () => json(READY),
      "POST /api/datasets": () => json({ detail: "The file has no rows." }, 400),
    });
    render(<AnalystApp />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText("Upload CSV"), new File([""], "empty.csv"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file has no rows.");
  });

  it("shows a dataset's details when it is clicked", async () => {
    withData({ "GET /api/datasets/sales": () => json(INFO) });
    render(<AnalystApp />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "sales" }));
    expect(await screen.findByText("2,000 rows, 2 columns")).toBeInTheDocument();
    expect(screen.getByText("TIMESTAMP")).toBeInTheDocument();
  });

  it("says the datasets are loading, and nothing more, until they arrive", async () => {
    const lists = later();
    serve({ "GET /api/datasets": lists.respond, "GET /api/agent/status": () => json(READY) });
    render(<AnalystApp />);
    expect(await screen.findByText("Loading datasets…")).toBeInTheDocument();
    expect(screen.queryByText("Start with some data")).toBeNull();
    expect(screen.queryByRole("button", { name: SUGGESTIONS[0] })).toBeNull();
    await lists.answer(0, json({ datasets: [] }));
    expect(screen.getByText("No datasets yet.")).toBeInTheDocument();
    expect(screen.queryByText("Loading datasets…")).toBeNull();
  });

  it("shows the dataset clicked last, even when an earlier click is answered later", async () => {
    const sales = later();
    withData({
      "GET /api/datasets": () => json({ datasets: ["sales", "costs"] }),
      "GET /api/datasets/sales": sales.respond,
      "GET /api/datasets/costs": () => json({ ...INFO, name: "costs" }),
    });
    render(<AnalystApp />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "sales" }));
    await user.click(screen.getByRole("button", { name: "costs" }));
    expect(await screen.findByRole("region", { name: "Details of costs" })).toBeInTheDocument();
    await sales.answer(0, json(INFO));
    expect(screen.getByRole("region", { name: "Details of costs" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Details of sales" })).toBeNull();
  });

  it("stays busy with an upload while a dataset is opened", async () => {
    const uploads = later();
    withData({
      "GET /api/datasets/sales": () => json(INFO),
      "POST /api/datasets": uploads.respond,
    });
    render(<AnalystApp />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText("Upload CSV"), new File(["a\n1\n"], "costs.csv"));
    expect(await screen.findByText("Uploading…")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "sales" }));
    await screen.findByRole("region", { name: "Details of sales" });
    expect(screen.getByText("Uploading…")).toBeInTheDocument();
    await uploads.answer(0, json({ ...INFO, name: "costs" }, 201));
    expect(screen.getByText("Upload CSV")).toBeInTheDocument();
  });
});

// React's strict mode runs each effect twice, as if the app appeared, went
// away and appeared again. The first request's answer must then be ignored.
describe("in strict mode, a late answer to the first request", () => {
  it.each([
    ["a list", json({ datasets: ["old"] })],
    ["an error", json({ detail: "Old news." }, 500)],
  ])("doesn't replace the datasets, when it is %s", async (_, late) => {
    const lists = later();
    serve({ "GET /api/datasets": lists.respond, "GET /api/agent/status": () => json(READY) });
    render(
      <StrictMode>
        <AnalystApp />
      </StrictMode>,
    );
    await vi.waitFor(() => {
      expect(lists.count()).toBe(2);
    });
    await lists.answer(1, json({ datasets: ["new"] }));
    expect(screen.getByRole("button", { name: "new" })).toBeInTheDocument();
    await lists.answer(0, late);
    expect(screen.getByRole("button", { name: "new" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "old" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("doesn't replace the agent's status", async () => {
    const checks = later();
    serve({
      "GET /api/datasets": () => json({ datasets: ["sales"] }),
      "GET /api/agent/status": checks.respond,
    });
    render(
      <StrictMode>
        <AnalystApp />
      </StrictMode>,
    );
    await vi.waitFor(() => {
      expect(checks.count()).toBe(2);
    });
    await checks.answer(1, json(READY));
    expect(screen.getByRole("button", { name: SUGGESTIONS[0] })).toBeEnabled();
    await checks.answer(0, json({ ready: false, detail: "Old news." }));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("button", { name: SUGGESTIONS[0] })).toBeEnabled();
  });
});

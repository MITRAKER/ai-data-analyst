import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useConversation } from "@/hooks/useConversation";
import { openStream, RUN, sseResponse } from "@/test/fakes";

describe("useConversation", () => {
  it("stops the running question when a new one is asked", async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        const signal = init?.signal ?? new AbortController().signal;
        signals.push(signal);
        return Promise.resolve(
          signals.length === 1
            ? openStream(signal, { type: "note", text: "Working on it." })
            : sseResponse(...RUN),
        );
      }),
    );
    const { result } = renderHook(() => useConversation());

    act(() => {
      result.current.ask("Who sold most?");
    });
    await waitFor(() => {
      expect(result.current.turns[0]?.steps).toHaveLength(1);
    });
    expect(result.current.busy).toBe(true);

    act(() => {
      result.current.ask("Which region sold most?");
    });
    await waitFor(() => {
      expect(result.current.turns[1]?.status).toBe("answered");
    });
    expect(signals[0]?.aborted).toBe(true);
    expect(result.current.turns[0]?.status).toBe("stopped");
    expect(result.current.busy).toBe(false);
  });

  it("does nothing when Stop is pressed with no question running", () => {
    const { result } = renderHook(() => useConversation());
    act(() => {
      result.current.stop();
    });
    expect(result.current.turns).toEqual([]);
    expect(result.current.busy).toBe(false);
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConversationView } from "@/components/ConversationView";
import { MAX_TURNS, type Turn } from "@/lib/conversation";

function turn(id: number): Turn {
  const question = `Question ${String(id)}`;
  return { id, question, steps: [], charts: [], answer: "", error: "", status: "running" };
}

function View({ turns }: { turns: Turn[] }) {
  return <ConversationView banner={null} turns={turns} hasData canAsk onAsk={vi.fn()} />;
}

describe("ConversationView", () => {
  it("shows a new question, even when the oldest one makes room for it", () => {
    const full = Array.from({ length: MAX_TURNS }, (_, i) => turn(i + 1));
    const { rerender } = render(<View turns={full} />);
    const view = screen.getByRole("list", { name: "Questions and answers" }).parentElement
      ?.parentElement;
    if (!view) {
      throw new Error("the scrolling view is missing");
    }
    // jsdom has no layout: 1000 pixels of content in a 400-pixel-high box.
    Object.defineProperty(view, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(view, "clientHeight", { configurable: true, value: 400 });
    view.scrollTop = 100; // the user scrolls up to read an old answer
    fireEvent.scroll(view);

    // The next question: the number of questions stays MAX_TURNS.
    const next = [...full.slice(1), turn(MAX_TURNS + 1)];
    rerender(<View turns={next} />);
    expect(screen.getByText(`Question ${String(MAX_TURNS + 1)}`)).toBeInTheDocument();
    expect(view.scrollTop).toBe(1000);
  });

  it("shows neither the welcome nor the suggestions until the datasets are known", () => {
    const { container } = render(
      <ConversationView banner={null} turns={[]} hasData={null} canAsk={false} onAsk={vi.fn()} />,
    );
    expect(container).toHaveTextContent("");
  });
});

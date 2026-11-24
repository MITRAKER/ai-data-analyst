import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QuestionForm } from "@/components/QuestionForm";

function setup(props: Partial<Parameters<typeof QuestionForm>[0]> = {}) {
  const onAsk = vi.fn();
  const onStop = vi.fn();
  render(<QuestionForm canAsk busy={false} onAsk={onAsk} onStop={onStop} {...props} />);
  return { onAsk, onStop, box: screen.getByRole("textbox", { name: "Your question" }) };
}

describe("QuestionForm", () => {
  it("sends the question on Enter and clears the box", async () => {
    const { onAsk, box } = setup();
    await userEvent.type(box, "  Who sold most?  {Enter}");
    expect(onAsk).toHaveBeenCalledWith("Who sold most?");
    expect(box).toHaveValue("");
  });

  it("starts a new line on Shift+Enter instead", async () => {
    const { onAsk, box } = setup();
    await userEvent.type(box, "Line one{Shift>}{Enter}{/Shift}line two");
    expect(onAsk).not.toHaveBeenCalled();
    expect(box).toHaveValue("Line one\nline two");
  });

  it("doesn't send while an input method is composing text", () => {
    const { onAsk, box } = setup();
    fireEvent.change(box, { target: { value: "質問です" } });
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onAsk).not.toHaveBeenCalled();
  });

  it("only sends a question of at least 3 characters", async () => {
    const { onAsk, box } = setup();
    await userEvent.type(box, "hi{Enter}");
    expect(onAsk).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("can't send when the agent isn't ready", async () => {
    const { onAsk, box } = setup({ canAsk: false });
    await userEvent.type(box, "Who sold most?{Enter}");
    expect(onAsk).not.toHaveBeenCalled();
  });

  it("offers Stop while the agent works", async () => {
    const { onStop } = setup({ busy: true });
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledOnce();
  });
});

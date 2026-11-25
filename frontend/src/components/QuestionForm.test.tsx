import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { QuestionForm } from "@/components/QuestionForm";

function setup(props: Partial<Parameters<typeof QuestionForm>[0]> = {}) {
  const onAsk = vi.fn();
  const onStop = vi.fn();
  render(<QuestionForm canAsk busy={false} onAsk={onAsk} onStop={onStop} {...props} />);
  return { onAsk, onStop, box: screen.getByRole("textbox", { name: "Your question" }) };
}

/** A form that is busy with an answer until Stop is pressed, as the app is. */
function setupBusyUntilStop() {
  const onAsk = vi.fn();
  function Form() {
    const [busy, setBusy] = useState(true);
    return (
      <QuestionForm
        canAsk
        busy={busy}
        onAsk={onAsk}
        onStop={() => {
          setBusy(false);
        }}
      />
    );
  }
  render(<Form />);
  return { onAsk, box: screen.getByRole("textbox", { name: "Your question" }) };
}

/** A form that turns busy when a question is sent, as the app does. */
function setupBusyAfterAsk() {
  const onStop = vi.fn();
  function Form() {
    const [busy, setBusy] = useState(false);
    return (
      <QuestionForm
        canAsk
        busy={busy}
        onAsk={() => {
          setBusy(true);
        }}
        onStop={onStop}
      />
    );
  }
  render(<Form />);
  return { onStop, box: screen.getByRole("textbox", { name: "Your question" }) };
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

  it("ignores the second click of a double-click on Ask, which lands on Stop", () => {
    const { onStop, box } = setupBusyAfterAsk();
    fireEvent.change(box, { target: { value: "Who sold most?" } });
    // A browser's double-click is two clicks in one place; the second has detail 2.
    fireEvent.click(screen.getByRole("button", { name: "Ask" }), { detail: 1 });
    const stop = screen.getByRole("button", { name: "Stop" });
    fireEvent.click(stop, { detail: 2 });
    expect(onStop).not.toHaveBeenCalled();
    // One click stops, and so does Enter or Space on the button (detail 0).
    fireEvent.click(stop, { detail: 1 });
    fireEvent.click(stop, { detail: 0 });
    expect(onStop).toHaveBeenCalledTimes(2);
  });

  it("ignores the second click of a double-click on Stop, which lands on Ask", () => {
    const { onAsk, box } = setupBusyUntilStop();
    // The next question, typed while the agent was still working.
    fireEvent.change(box, { target: { value: "And by month?" } });
    fireEvent.click(screen.getByRole("button", { name: "Stop" }), { detail: 1 });
    const ask = screen.getByRole("button", { name: "Ask" });
    fireEvent.click(ask, { detail: 2 });
    expect(onAsk).not.toHaveBeenCalled();
    expect(box).toHaveValue("And by month?");
    // One click sends it.
    fireEvent.click(ask, { detail: 1 });
    expect(onAsk).toHaveBeenCalledWith("And by month?");
  });

  it("moves the keyboard focus to the box after Enter on Ask, not to Stop", async () => {
    const { box } = setupBusyAfterAsk();
    const user = userEvent.setup();
    await user.type(box, "Who sold most?");
    screen.getByRole("button", { name: "Ask" }).focus();
    await user.keyboard("{Enter}");
    // On Stop, a second Enter would stop at once; on nothing, the focus is lost.
    expect(screen.getByRole("button", { name: "Stop" })).not.toHaveFocus();
    expect(box).toHaveFocus();
  });

  it("moves the keyboard focus to the box after Space on Stop", async () => {
    const { box } = setupBusyUntilStop();
    const user = userEvent.setup();
    screen.getByRole("button", { name: "Stop" }).focus();
    await user.keyboard(" ");
    expect(screen.getByRole("button", { name: "Ask" })).toBeInTheDocument();
    expect(box).toHaveFocus();
  });

  it("leaves the focus alone after a click, which would open a phone's keyboard", async () => {
    const { box } = setupBusyUntilStop();
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(screen.getByRole("button", { name: "Ask" })).toBeInTheDocument();
    expect(box).not.toHaveFocus();
  });

  it("gives the app its text box, to move the focus there", () => {
    const inputRef = createRef<HTMLTextAreaElement>();
    const { box } = setup({ inputRef });
    expect(inputRef.current).toBe(box);
  });
});

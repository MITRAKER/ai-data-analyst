"use client";

import {
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
  type SubmitEvent,
} from "react";

import styles from "./ConversationView.module.css";

/** The API's limits for a question (AskRequest in backend/app/main.py). */
export const MIN_QUESTION_CHARS = 3;
export const MAX_QUESTION_CHARS = 2_000;

interface Props {
  canAsk: boolean;
  busy: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
  /** The text box, so that the app can move the keyboard focus to it. */
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}

/**
 * Check a click on Ask or Stop. Stop appears where Ask was, the moment the
 * question starts, and Ask comes back when it ends. So the second click of a
 * double-click on one button lands on the other. `detail` counts the clicks:
 * 2 is that second click, which both buttons ignore. 0 is a press of Enter or
 * Space: the button is about to go away, so the keyboard focus moves to the
 * text box first.
 *
 * @returns whether the button may do its job.
 */
function acceptClick(event: MouseEvent<HTMLButtonElement>): boolean {
  if (event.detail > 1) {
    event.preventDefault(); // on Ask: don't send
    return false;
  }
  if (event.detail === 0) {
    event.currentTarget.form?.querySelector("textarea")?.focus();
  }
  return true;
}

/** How long after a key pressed Stop an Enter in the box still belongs to that press. */
const KEY_STOP_MS = 500;

/**
 * Stop, and a check for Enter in the text box. After Enter on Stop, the focus
 * is in the box, where Enter sends. A second press of Enter, or the key held
 * down, must not send the question typed while the agent was working.
 */
function useStop(onStop: () => void) {
  const keyStopAt = useRef(Number.NEGATIVE_INFINITY);
  return {
    stop: (event: MouseEvent<HTMLButtonElement>) => {
      if (acceptClick(event)) {
        if (event.detail === 0) {
          keyStopAt.current = event.timeStamp;
        }
        onStop();
      }
    },
    /** Is this a new press of Enter, not a held key or a second press after Stop? */
    isNewEnter: (event: KeyboardEvent<HTMLTextAreaElement>) =>
      !event.repeat && event.timeStamp - keyStopAt.current >= KEY_STOP_MS,
  };
}

/** The box for a question. Enter sends it; Shift+Enter starts a new line. */
export function QuestionForm({ canAsk, busy, onAsk, onStop, inputRef }: Props) {
  const [text, setText] = useState("");
  const question = text.trim();
  const ready = canAsk && !busy && question.length >= MIN_QUESTION_CHARS;
  const { stop, isNewEnter } = useStop(onStop);

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready) {
      onAsk(question);
      setText("");
    }
  }

  function sendOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (isNewEnter(event)) {
        event.currentTarget.form?.requestSubmit();
      }
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <label htmlFor="question" className="visually-hidden">
        Your question
      </label>
      <textarea
        ref={inputRef}
        id="question"
        className={styles.input}
        value={text}
        rows={2}
        maxLength={MAX_QUESTION_CHARS}
        placeholder="Ask a question about your data…"
        onChange={(event) => {
          setText(event.target.value);
        }}
        onKeyDown={sendOnEnter}
      />
      {/* Different keys make two different buttons, so the keyboard focus on
          Ask doesn't move over to Stop: pressing Enter twice can't stop. */}
      {busy ? (
        <button key="stop" type="button" className={styles.stop} onClick={stop}>
          Stop
        </button>
      ) : (
        <button
          key="ask"
          type="submit"
          className={styles.send}
          disabled={!ready}
          onClick={acceptClick}
        >
          Ask
        </button>
      )}
    </form>
  );
}

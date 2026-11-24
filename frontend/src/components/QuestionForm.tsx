"use client";

import {
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

/** The box for a question. Enter sends it; Shift+Enter starts a new line. */
export function QuestionForm({ canAsk, busy, onAsk, onStop, inputRef }: Props) {
  const [text, setText] = useState("");
  const question = text.trim();
  const ready = canAsk && !busy && question.length >= MIN_QUESTION_CHARS;

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready) {
      onAsk(question);
      setText("");
    }
  }

  function stop(event: MouseEvent<HTMLButtonElement>) {
    // Stop appears where Ask was, the moment the question starts. So the
    // second click of a double-click on Ask lands on Stop, and would stop the
    // question at once. `detail` counts the clicks: 2 is that second click.
    if (event.detail <= 1) {
      onStop();
    }
  }

  function sendOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
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
        <button key="ask" type="submit" className={styles.send} disabled={!ready}>
          Ask
        </button>
      )}
    </form>
  );
}

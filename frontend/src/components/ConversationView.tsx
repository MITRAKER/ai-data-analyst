"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { TurnView } from "@/components/TurnView";
import type { Turn } from "@/lib/conversation";

import styles from "./ConversationView.module.css";

/** Questions that work well with data/sample_sales.csv. */
export const SUGGESTIONS = [
  "Which region brought in the most revenue?",
  "Show the monthly revenue as a line chart.",
  "Which products sell best online, and which in retail stores?",
];

/** How close to the bottom (in pixels) still counts as "at the bottom". */
const PINNED_DISTANCE = 80;

interface Props {
  banner: ReactNode;
  turns: Turn[];
  hasData: boolean;
  canAsk: boolean;
  onAsk: (question: string) => void;
}

/**
 * All questions and answers. While the agent works, the view follows the new
 * steps, unless the user has scrolled up to read something.
 */
export function ConversationView({ banner, turns, hasData, canAsk, onAsk }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const count = useRef(turns.length);

  useEffect(() => {
    const element = box.current;
    if (turns.length > count.current) {
      pinned.current = true; // a new question: always show it
    }
    count.current = turns.length;
    if (element && pinned.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [turns]);

  function onScroll() {
    const element = box.current;
    if (element) {
      const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
      pinned.current = distance < PINNED_DISTANCE;
    }
  }

  return (
    <div ref={box} className={styles.scroll} onScroll={onScroll}>
      <div className={styles.column}>
        {banner}
        {turns.length === 0 ? (
          <EmptyState hasData={hasData} canAsk={canAsk} onAsk={onAsk} />
        ) : (
          <ol className={styles.turns} aria-label="Questions and answers">
            {turns.map((turn) => (
              <TurnView key={turn.id} turn={turn} />
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function EmptyState({ hasData, canAsk, onAsk }: Omit<Props, "banner" | "turns">) {
  if (!hasData) {
    return (
      <div className={styles.empty}>
        <h2>Start with some data</h2>
        <p>
          Upload a CSV file on the left. To try the app, use <code>data/sample_sales.csv</code> from
          this project: 2,000 orders from 2025.
        </p>
      </div>
    );
  }
  return (
    <div className={styles.empty}>
      <h2>Ask a question</h2>
      <p>The agent writes SQL and Python, runs them, and shows you every step. For example:</p>
      <ul className={styles.suggestions}>
        {SUGGESTIONS.map((question) => (
          <li key={question}>
            <button
              type="button"
              disabled={!canAsk}
              onClick={() => {
                onAsk(question);
              }}
            >
              {question}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

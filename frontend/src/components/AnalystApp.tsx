"use client";

import { ConversationView } from "@/components/ConversationView";
import { DatasetPanel } from "@/components/DatasetPanel";
import { QuestionForm } from "@/components/QuestionForm";
import { StatusBanner } from "@/components/StatusBanner";
import { useAgentStatus } from "@/hooks/useAgentStatus";
import { useConversation } from "@/hooks/useConversation";
import { useDatasets } from "@/hooks/useDatasets";

import styles from "./AnalystApp.module.css";

/** The whole app: datasets on the left, the conversation on the right. */
export function AnalystApp() {
  const datasets = useDatasets();
  const conversation = useConversation();
  const agent = useAgentStatus();
  const canAsk = agent.kind === "ready" && datasets.names.length > 0;

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <h1 className={styles.title}>AI Data Analyst</h1>
        <span className={styles.tagline}>Ask questions about your data in plain English.</span>
      </header>
      <DatasetPanel datasets={datasets} />
      <main className={styles.main}>
        <ConversationView
          banner={<StatusBanner agent={agent} />}
          turns={conversation.turns}
          hasData={datasets.names.length > 0}
          canAsk={canAsk && !conversation.busy}
          onAsk={conversation.ask}
        />
        <div className={styles.footer}>
          <div className={styles.column}>
            <QuestionForm
              canAsk={canAsk}
              busy={conversation.busy}
              onAsk={conversation.ask}
              onStop={conversation.stop}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

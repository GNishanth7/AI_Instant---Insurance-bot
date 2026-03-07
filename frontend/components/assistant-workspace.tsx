"use client";

import { useEffect, useState } from "react";

import { api, ApiError } from "../lib/api";
import type {
  ChatResponse,
  ConversationMessage,
  PlanDetail,
  PlanSummary
} from "../lib/types";
import { ContextPanel, type ContextView } from "./context-panel";
import { ConversationPanel } from "./conversation-panel";
import { PlanEntryScreen } from "./plan-entry-screen";
import { WorkspaceTopbar } from "./workspace-topbar";

const MAX_QUESTION_LENGTH = 500;
const STARTER_REPLIES = [
  "Does my insurance cover MRI?",
  "What is the dental cover?",
  "I want to file a claim for physiotherapy",
  "I want to book a physiotherapy appointment"
];
const SELECTED_PLAN_KEY = "health-plan-assistant:selected-plan";

function buildInitialMessage(): ConversationMessage {
  return {
    id: "assistant-initial",
    role: "assistant",
    content:
      "Ask about cover, file a claim, or book an appointment. Use the quick actions to move faster when you want to stay in the workflow.",
    quickReplies: STARTER_REPLIES
  };
}

function conversationFallback(message: string): ConversationMessage {
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    content: message,
    quickReplies: STARTER_REPLIES
  };
}

function mapResponse(response: ChatResponse): ConversationMessage {
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    content: response.content,
    citation: response.citation,
    sources: response.sources,
    claimSummary: response.claim_summary,
    appointmentSummary: response.appointment_summary,
    disclaimer: response.disclaimer,
    quickReplies: response.quick_replies,
    inputMode: response.input_mode,
    inputContext: response.input_context
  };
}

function getLatestAssistant(messages: ConversationMessage[]) {
  return [...messages].reverse().find((message) => message.role === "assistant") ?? null;
}

function getLatestClaimSummary(messages: ConversationMessage[]) {
  return [...messages]
    .reverse()
    .find((message) => message.claimSummary)?.claimSummary ?? null;
}

function getLatestAppointmentSummary(messages: ConversationMessage[]) {
  return [...messages]
    .reverse()
    .find((message) => message.appointmentSummary)?.appointmentSummary ?? null;
}

export function AssistantWorkspace() {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [selectedPlan, setSelectedPlan] = useState<PlanDetail | null>(null);
  const [planConfirmed, setPlanConfirmed] = useState(false);
  const [messages, setMessages] = useState<ConversationMessage[]>([buildInitialMessage()]);
  const [input, setInput] = useState("");
  const [dateInputValue, setDateInputValue] = useState("");
  const [sessionId, setSessionId] = useState<string>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [activeContextView, setActiveContextView] = useState<ContextView>("overview");

  useEffect(() => {
    void loadPlans();
  }, []);

  useEffect(() => {
    if (planConfirmed && selectedPlanId) {
      void loadPlan(selectedPlanId);
      window.localStorage.setItem(SELECTED_PLAN_KEY, selectedPlanId);
    }
  }, [planConfirmed, selectedPlanId]);

  const latestAssistant = getLatestAssistant(messages);
  const inputMode = latestAssistant?.inputMode ?? "text";
  const inputContext = latestAssistant?.inputContext ?? "";

  useEffect(() => {
    if (inputMode !== "date") {
      setDateInputValue("");
    }
  }, [inputMode, inputContext]);

  async function loadPlans() {
    try {
      setLoading(true);
      setError("");
      const data = await api.listPlans();
      setPlans(data);
      const storedPlanId = window.localStorage.getItem(SELECTED_PLAN_KEY);
      const initialPlanId =
        data.find((plan) => plan.id === storedPlanId)?.id ?? data[0]?.id ?? "";
      setSelectedPlanId(initialPlanId);
    } catch {
      setError("Could not load plans.");
    } finally {
      setLoading(false);
    }
  }

  async function loadPlan(planId: string) {
    try {
      const data = await api.getPlan(planId);
      setSelectedPlan(data);
      return true;
    } catch {
      setError("Could not load plan details.");
      return false;
    }
  }

  async function handlePlanContinue() {
    if (!selectedPlanId) {
      return;
    }

    setLoading(true);
    const loaded = await loadPlan(selectedPlanId);
    setLoading(false);

    if (loaded) {
      setPlanConfirmed(true);
      setActiveContextView("overview");
    }
  }

  async function handlePlanChange(nextPlanId: string) {
    if (!nextPlanId || nextPlanId === selectedPlanId) {
      return;
    }

    if (sessionId) {
      try {
        await api.resetSession(sessionId);
      } catch {
        // Ignore reset failures during plan switches.
      }
    }

    setSelectedPlanId(nextPlanId);
    setSelectedPlan(null);
    setSessionId(undefined);
    setMessages([buildInitialMessage()]);
    setInput("");
    setDateInputValue("");
    setError("");
    setActiveContextView("overview");
  }

  async function handleRebuild() {
    if (!selectedPlanId) {
      return;
    }

    try {
      setError("");
      await api.rebuildPlan(selectedPlanId);
      await loadPlan(selectedPlanId);
    } catch {
      setError("Could not rebuild the selected plan index.");
    }
  }

  async function handleResetConversation() {
    if (sessionId) {
      try {
        await api.resetSession(sessionId);
      } catch {
        // Ignore reset failures and clear the local state anyway.
      }
    }

    setMessages([buildInitialMessage()]);
    setSessionId(undefined);
    setInput("");
    setDateInputValue("");
    setError("");
    setActiveContextView("overview");
  }

  async function handleSubmit(rawMessage: string) {
    const cleanedMessage = rawMessage.trim();
    if (!cleanedMessage || !selectedPlanId || !planConfirmed || submitting) {
      return;
    }

    if (cleanedMessage.length > MAX_QUESTION_LENGTH) {
      setMessages((current) => [
        ...current,
        conversationFallback(
          `Questions must be ${MAX_QUESTION_LENGTH} characters or fewer.`
        )
      ]);
      return;
    }

    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: cleanedMessage
      }
    ]);
    setInput("");
    setDateInputValue("");
    setSubmitting(true);
    setError("");

    try {
      const response = await api.chat(selectedPlanId, cleanedMessage, sessionId);
      setSessionId(response.session_id);
      setMessages((current) => [...current, mapResponse(response)]);

      if (response.claim_summary || response.appointment_summary) {
        setActiveContextView("workflow");
      } else if (response.sources.length) {
        setActiveContextView("sources");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const quickReplies = latestAssistant?.quickReplies?.length
    ? latestAssistant.quickReplies
    : STARTER_REPLIES;
  const latestSources = latestAssistant?.sources ?? [];
  const latestClaimSummary = getLatestClaimSummary(messages);
  const latestAppointmentSummary = getLatestAppointmentSummary(messages);
  const busy = loading || submitting;

  if (!planConfirmed) {
    return (
      <PlanEntryScreen
        error={error}
        loading={loading}
        plans={plans}
        selectedPlanId={selectedPlanId}
        onContinue={() => {
          void handlePlanContinue();
        }}
        onSelectPlan={setSelectedPlanId}
      />
    );
  }

  return (
    <main className="app-shell">
      <WorkspaceTopbar
        busy={busy}
        plans={plans}
        selectedPlan={selectedPlan}
        selectedPlanId={selectedPlanId}
        onPlanChange={(planId) => {
          void handlePlanChange(planId);
        }}
        onRebuild={() => {
          void handleRebuild();
        }}
        onReset={() => {
          void handleResetConversation();
        }}
      />

      <section className="workspace-grid">
        <ConversationPanel
          dateInputValue={dateInputValue}
          error={error}
          input={input}
          inputContext={inputContext}
          inputMode={inputMode}
          maxQuestionLength={MAX_QUESTION_LENGTH}
          messages={messages}
          quickReplies={quickReplies}
          selectedPlan={selectedPlan}
          submitting={submitting}
          onDateInputChange={setDateInputValue}
          onInputChange={setInput}
          onQuickReply={(value) => {
            void handleSubmit(value);
          }}
          onDateSubmit={() => {
            void handleSubmit(toWorkflowDate(dateInputValue));
          }}
          onSubmit={() => {
            void handleSubmit(input);
          }}
        />

        <ContextPanel
          activeView={activeContextView}
          appointmentSummary={latestAppointmentSummary}
          claimSummary={latestClaimSummary}
          latestSources={latestSources}
          selectedPlan={selectedPlan}
          onViewChange={setActiveContextView}
        />
      </section>
    </main>
  );
}

function toWorkflowDate(isoDate: string) {
  const [year, month, day] = isoDate.split("-");
  if (!year || !month || !day) {
    return isoDate;
  }
  return `${day}/${month}/${year}`;
}

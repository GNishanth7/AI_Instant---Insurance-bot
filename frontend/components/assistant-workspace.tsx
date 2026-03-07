"use client";

import { FormEvent, useEffect, useState, useTransition } from "react";

import { api, ApiError } from "../lib/api";
import type {
  AppointmentSummary,
  ChatResponse,
  ClaimSummary,
  ConversationMessage,
  PlanDetail,
  PlanSummary
} from "../lib/types";
import { ChatMessage } from "./chat-message";

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
      "Ask directly about cover, file a claim, or start an appointment request. Simple next steps appear as clickable actions.",
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

function latestAssistant(messages: ConversationMessage[]) {
  return [...messages].reverse().find((message) => message.role === "assistant") ?? null;
}

function latestClaimSummary(messages: ConversationMessage[]) {
  return [...messages]
    .reverse()
    .find((message) => message.claimSummary)?.claimSummary ?? null;
}

function latestAppointmentSummary(messages: ConversationMessage[]) {
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
  const [composer, setComposer] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    void loadPlans();
  }, []);

  useEffect(() => {
    if (!planConfirmed || !selectedPlanId) {
      return;
    }
    window.localStorage.setItem(SELECTED_PLAN_KEY, selectedPlanId);
    void loadPlan(selectedPlanId);
  }, [planConfirmed, selectedPlanId]);

  const activeAssistant = latestAssistant(messages);
  const quickReplies = activeAssistant?.quickReplies?.length
    ? activeAssistant.quickReplies
    : STARTER_REPLIES;
  const latestSources = activeAssistant?.sources ?? [];
  const currentClaimSummary = latestClaimSummary(messages);
  const currentAppointmentSummary = latestAppointmentSummary(messages);

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
    } catch (err) {
      setError(getErrorMessage(err, "Could not load plans."));
    } finally {
      setLoading(false);
    }
  }

  async function loadPlan(planId: string): Promise<boolean> {
    if (!planId) {
      return false;
    }
    try {
      setError("");
      const detail = await api.getPlan(planId);
      startTransition(() => {
        setSelectedPlan(detail);
      });
      return true;
    } catch (err) {
      setError(getErrorMessage(err, "Could not load the selected plan."));
      return false;
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
        // Ignore reset errors during plan switches.
      }
    }
    startTransition(() => {
      setSelectedPlanId(nextPlanId);
      setSelectedPlan(null);
      setSessionId(undefined);
      setMessages([buildInitialMessage()]);
      setComposer("");
      setError("");
    });
  }

  async function handlePlanContinue() {
    if (!selectedPlanId) {
      return;
    }
    setLoading(true);
    try {
      const loaded = await loadPlan(selectedPlanId);
      if (loaded) {
        startTransition(() => {
          setPlanConfirmed(true);
        });
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleRebuild() {
    if (!selectedPlanId) {
      return;
    }
    try {
      setError("");
      await api.rebuildPlan(selectedPlanId);
      await loadPlan(selectedPlanId);
    } catch (err) {
      setError(getErrorMessage(err, "Could not rebuild the plan index."));
    }
  }

  async function handleResetConversation() {
    if (sessionId) {
      try {
        await api.resetSession(sessionId);
      } catch {
        // Ignore reset errors and reset client state anyway.
      }
    }
    startTransition(() => {
      setMessages([buildInitialMessage()]);
      setSessionId(undefined);
      setComposer("");
      setError("");
    });
  }

  async function submitMessage(rawMessage: string) {
    const cleanedMessage = rawMessage.trim();
    if (!cleanedMessage || !selectedPlanId || !planConfirmed) {
      return;
    }

    if (cleanedMessage.length > MAX_QUESTION_LENGTH) {
      startTransition(() => {
        setMessages((current) => [
          ...current,
          conversationFallback(
            `Questions must be ${MAX_QUESTION_LENGTH} characters or fewer.`
          )
        ]);
      });
      return;
    }

    const userMessage: ConversationMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: cleanedMessage
    };

    startTransition(() => {
      setMessages((current) => [...current, userMessage]);
      setComposer("");
      setError("");
    });
    setIsSubmitting(true);

    try {
      const response = await api.chat(selectedPlanId, cleanedMessage, sessionId);
      setSessionId(response.session_id);
      const assistantMessage = mapResponseToMessage(response);
      startTransition(() => {
        setMessages((current) => [...current, assistantMessage]);
      });
    } catch (err) {
      startTransition(() => {
        setMessages((current) => [
          ...current,
          conversationFallback(getErrorMessage(err, "Could not reach the backend."))
        ]);
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleComposerSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitMessage(composer);
  }

  if (!planConfirmed) {
    return (
      <main className="entry">
        <section className="entry__hero card">
          <div className="entry__copy">
            <span className="eyebrow eyebrow--dark">Employee benefits assistant</span>
            <h1>Pick your plan first, then ask questions, file claims, or draft appointments.</h1>
            <p>
              The answers stay grounded in your selected policy data. Gemini handles the final
              answer wording, while retrieval and workflow logic stay tied to your plan.
            </p>
            <div className="entry__chips">
              <span className="pill pill--dark">Gemini answer generation</span>
              <span className="pill pill--dark">FAISS retrieval</span>
              <span className="pill pill--dark">Claim + appointment workflows</span>
            </div>
          </div>

          <div className="entry__panel">
            <div className="entry__panel-head">
              <span className="eyebrow eyebrow--dark">Available plans</span>
              <h2>Select your policy plan</h2>
            </div>
            <div className="plan-grid">
              {plans.map((plan) => {
                const selected = selectedPlanId === plan.id;
                return (
                  <button
                    className={`plan-card ${selected ? "plan-card--selected" : ""}`}
                    key={plan.id}
                    onClick={() => setSelectedPlanId(plan.id)}
                    type="button"
                  >
                    <span className="plan-card__name">{plan.display_name}</span>
                    <span className="plan-card__meta">{plan.benefit_count} benefit rows</span>
                    <span className="plan-card__meta">
                      {plan.category_count} categories, {plan.section_count} sections
                    </span>
                  </button>
                );
              })}
            </div>
            {error ? <div className="banner banner--error">{error}</div> : null}
            <button
              className="button button--primary entry__continue"
              disabled={!selectedPlanId || loading}
              onClick={() => void handlePlanContinue()}
              type="button"
            >
              {loading ? "Loading plan..." : "Continue with selected plan"}
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="workspace">
      <section className="workspace__shell">
        <aside className="workspace__sidebar card card--dark">
          <div className="sidebar__header">
            <span className="eyebrow">Kota-style workspace</span>
            <h1>Member support console</h1>
            <p>
              A private, plan-grounded assistant for cover lookup, claim drafting, and appointment
              request capture.
            </p>
          </div>

          <label className="field">
            <span className="field__label">Policy plan</span>
            <select
              className="field__control"
              onChange={(event) => {
                void handlePlanChange(event.target.value);
              }}
              value={selectedPlanId}
            >
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.display_name}
                </option>
              ))}
            </select>
          </label>

          <div className="sidebar__actions">
            <button
              className="button button--light"
              onClick={() => void handleRebuild()}
              type="button"
            >
              Rebuild index
            </button>
            <button
              className="button button--ghost"
              onClick={() => void handleResetConversation()}
              type="button"
            >
              New conversation
            </button>
          </div>

          <div className="stats">
            <article className="stat-card">
              <span>Benefits</span>
              <strong>{selectedPlan?.benefit_count ?? "--"}</strong>
            </article>
            <article className="stat-card">
              <span>Categories</span>
              <strong>{selectedPlan?.category_count ?? "--"}</strong>
            </article>
            <article className="stat-card">
              <span>Sections</span>
              <strong>{selectedPlan?.section_count ?? "--"}</strong>
            </article>
          </div>

          <div className="sidebar__notes">
            <div className="info-tile">
              <span>Retrieval mode</span>
              <strong>
                {selectedPlan?.vector_enabled ? "Vector index" : "Keyword fallback"}
              </strong>
            </div>
            <div className="info-tile">
              <span>Answer generation</span>
              <strong>
                {selectedPlan?.ai_generation_enabled ? "Gemini 2.5 Flash" : "Grounded fallback"}
              </strong>
            </div>
          </div>
        </aside>

        <section className="workspace__main">
          <header className="hero card">
            <div className="hero__badges">
              <span className="pill">Plan selected</span>
              <span className="pill pill--soft">
                {selectedPlan?.display_name ?? "Loading plan"}
              </span>
              <span className="pill pill--soft">
                {selectedPlan?.ai_generation_enabled
                  ? "Gemini answer generation"
                  : "Grounded fallback"}
              </span>
            </div>
            <div className="hero__grid">
              <div>
                <span className="eyebrow eyebrow--dark">Coverage intelligence</span>
                <h2>Ask about cover, file a claim, or draft an appointment request from one workspace.</h2>
                <p>
                  Retrieved policy chunks stay grounded in the selected plan. Gemini rewrites the
                  final answer into something that feels like a real assistant instead of a raw
                  template, while workflows still collect structured data step by step.
                </p>
              </div>
              <div className="hero__spotlight">
                <div className="hero__spotlight-label">Starter actions</div>
                <div className="hero__chips">
                  {STARTER_REPLIES.map((reply) => (
                    <button
                      className="chip"
                      key={reply}
                      onClick={() => void submitMessage(reply)}
                      type="button"
                    >
                      {reply}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </header>

          <section className="chat card">
            <div className="chat__header">
              <div>
                <span className="eyebrow eyebrow--dark">Conversation</span>
                <h3>Grounded answers with structured claim and appointment flows</h3>
              </div>
              <div className={`status ${isSubmitting || isPending ? "status--busy" : ""}`}>
                {loading ? "Loading" : isSubmitting || isPending ? "Working" : "Ready"}
              </div>
            </div>

            {error ? <div className="banner banner--error">{error}</div> : null}

            <div className="chat__timeline">
              {messages.map((message) => (
                <ChatMessage key={message.id} message={message} />
              ))}
            </div>

            <div className="reply-bar">
              <div className="reply-bar__label">Quick replies</div>
              <div className="reply-bar__buttons">
                {quickReplies.map((reply) => (
                  <button
                    className="button button--reply"
                    key={reply}
                    onClick={() => void submitMessage(reply)}
                    type="button"
                  >
                    {reply}
                  </button>
                ))}
              </div>
            </div>

            <form className="composer" onSubmit={handleComposerSubmit}>
              <textarea
                className="composer__input"
                disabled={isSubmitting || loading || !selectedPlanId}
                maxLength={MAX_QUESTION_LENGTH}
                onChange={(event) => setComposer(event.target.value)}
                placeholder="Ask about cover, continue a claim, or draft an appointment request."
                rows={4}
                value={composer}
              />
              <div className="composer__footer">
                <span>{composer.length}/{MAX_QUESTION_LENGTH}</span>
                <button
                  className="button button--primary"
                  disabled={isSubmitting || loading || !composer.trim() || !selectedPlanId}
                  type="submit"
                >
                  {isSubmitting ? "Sending..." : "Send message"}
                </button>
              </div>
            </form>
          </section>
        </section>

        <aside className="workspace__rail">
          <section className="card rail-card">
            <span className="eyebrow eyebrow--dark">Selected plan</span>
            <h3>{selectedPlan?.display_name ?? "Waiting for plan details"}</h3>
            <p>
              {selectedPlan
                ? "Answers are generated from retrieved policy context and surfaced with citations."
                : "Plan details will appear here once the frontend loads the current plan."}
            </p>
            <div className="rail-card__grid">
              <div className="rail-card__item">
                <span>Benefits</span>
                <strong>{selectedPlan?.benefit_count ?? "--"}</strong>
              </div>
              <div className="rail-card__item">
                <span>AI mode</span>
                <strong>{selectedPlan?.ai_generation_enabled ? "Gemini" : "Fallback"}</strong>
              </div>
            </div>
          </section>

          <section className="card rail-card">
            <span className="eyebrow eyebrow--dark">Latest sources</span>
            <h3>{latestSources.length ? `${latestSources.length} retrieved matches` : "No sources yet"}</h3>
            <div className="source-list">
              {latestSources.length ? (
                latestSources.slice(0, 4).map((source) => (
                  <article className="source-item" key={`${source.citation}-${source.score}`}>
                    <div className="source-item__score">{source.score.toFixed(2)}</div>
                    <div className="source-item__body">
                      <strong>{source.benefit}</strong>
                      <p>{source.coverage}</p>
                      <span>{source.citation}</span>
                    </div>
                  </article>
                ))
              ) : (
                <p className="empty-copy">
                  Retrieved citations will appear here after the first coverage or workflow query.
                </p>
              )}
            </div>
          </section>

          <section className="card rail-card">
            <span className="eyebrow eyebrow--dark">Claim draft</span>
            <h3>{currentClaimSummary ? "Latest claim draft" : "No claim summary yet"}</h3>
            {currentClaimSummary ? (
              <dl className="mini-summary">
                <div>
                  <dt>Treatment</dt>
                  <dd>{currentClaimSummary.claim_type || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Date</dt>
                  <dd>{currentClaimSummary.date_of_service || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Amount</dt>
                  <dd>
                    {currentClaimSummary.amount_eur === null
                      ? "Not provided"
                      : `EUR ${currentClaimSummary.amount_eur.toFixed(2)}`}
                  </dd>
                </div>
                <div>
                  <dt>Receipt</dt>
                  <dd>{formatBool(currentClaimSummary.has_receipt)}</dd>
                </div>
              </dl>
            ) : (
              <p className="empty-copy">
                Start with a claim message such as "I want to file a claim for physiotherapy".
              </p>
            )}
          </section>

          <section className="card rail-card">
            <span className="eyebrow eyebrow--dark">Appointment request</span>
            <h3>{currentAppointmentSummary ? "Latest appointment draft" : "No appointment summary yet"}</h3>
            {currentAppointmentSummary ? (
              <dl className="mini-summary">
                <div>
                  <dt>Type</dt>
                  <dd>{currentAppointmentSummary.appointment_type || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Mode</dt>
                  <dd>{currentAppointmentSummary.appointment_mode || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Date</dt>
                  <dd>{currentAppointmentSummary.preferred_date || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Time</dt>
                  <dd>{currentAppointmentSummary.preferred_time_window || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Location</dt>
                  <dd>{currentAppointmentSummary.location || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Covered</dt>
                  <dd>{formatBool(currentAppointmentSummary.policy_covered)}</dd>
                </div>
              </dl>
            ) : (
              <p className="empty-copy">
                Start with an appointment message such as "I want to book a physiotherapy appointment".
              </p>
            )}
          </section>
        </aside>
      </section>
    </main>
  );
}

function mapResponseToMessage(response: ChatResponse): ConversationMessage {
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    content: response.content,
    citation: response.citation,
    sources: response.sources,
    claimSummary: response.claim_summary,
    appointmentSummary: response.appointment_summary,
    disclaimer: response.disclaimer,
    quickReplies: response.quick_replies
  };
}

function formatBool(value: boolean | null | undefined) {
  if (value === null || value === undefined) {
    return "Not provided";
  }
  return value ? "Yes" : "No";
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

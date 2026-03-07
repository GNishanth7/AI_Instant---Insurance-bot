"use client";

import { FormEvent } from "react";

import type { ConversationMessage, PlanDetail } from "../lib/types";
import { ChatMessage } from "./chat-message";

interface ConversationPanelProps {
  dateInputValue: string;
  error: string;
  input: string;
  inputContext: string;
  inputMode: string;
  maxQuestionLength: number;
  messages: ConversationMessage[];
  quickReplies: string[];
  selectedPlan: PlanDetail | null;
  submitting: boolean;
  onDateInputChange: (value: string) => void;
  onDateSubmit: () => void;
  onInputChange: (value: string) => void;
  onQuickReply: (value: string) => void;
  onSubmit: () => void;
}

export function ConversationPanel({
  dateInputValue,
  error,
  input,
  inputContext,
  inputMode,
  maxQuestionLength,
  messages,
  quickReplies,
  selectedPlan,
  submitting,
  onDateInputChange,
  onDateSubmit,
  onInputChange,
  onQuickReply,
  onSubmit
}: ConversationPanelProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  function handleDateSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onDateSubmit();
  }

  return (
    <section className="conversation-panel card">
      <div className="panel-heading">
        <div>
          <span className="eyebrow eyebrow--dark">Conversation</span>
          <h2>Ask a question or continue a workflow</h2>
        </div>
        <div className="badge-row">
          <span className="badge">{selectedPlan?.display_name ?? "No plan selected"}</span>
          <span className="badge badge--soft">
            {selectedPlan?.ai_generation_enabled ? "Gemini on" : "Grounded fallback"}
          </span>
        </div>
      </div>

      {error ? <div className="banner banner--error">{error}</div> : null}

      <div className="starter-card">
        <span className="section-label">Quick actions</span>
        <div className="chip-row">
          {quickReplies.map((reply) => (
            <button
              className="chip"
              disabled={submitting}
              key={reply}
              onClick={() => onQuickReply(reply)}
              type="button"
            >
              {reply}
            </button>
          ))}
        </div>
      </div>

      <div className="timeline">
        {messages.map((message) => (
          <ChatMessage key={message.id} message={message} />
        ))}
      </div>

      {inputMode === "date" ? (
        <form className="date-card" onSubmit={handleDateSubmit}>
          <div className="date-card__copy">
            <span className="section-label">Calendar input</span>
            <strong>{dateFieldLabel(inputContext)}</strong>
            <p>Pick the date directly instead of typing it manually.</p>
          </div>
          <div className="date-card__controls">
            <input
              className="field__control field__control--date"
              max={dateFieldMax(inputContext)}
              min={dateFieldMin(inputContext)}
              onChange={(event) => onDateInputChange(event.target.value)}
              type="date"
              value={dateInputValue}
            />
            <button
              className="button button--secondary"
              disabled={!dateInputValue || submitting}
              type="submit"
            >
              Use selected date
            </button>
          </div>
        </form>
      ) : null}

      <form className="composer-card" onSubmit={handleSubmit}>
        <label className="composer-card__label" htmlFor="assistant-input">
          Type your next message
        </label>
        <textarea
          className="composer-card__input"
          disabled={submitting}
          id="assistant-input"
          maxLength={maxQuestionLength}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="Ask about cover, submit the next workflow detail, or use a quick action above."
          rows={4}
          value={input}
        />
        <div className="composer-card__footer">
          <span>{input.length}/{maxQuestionLength}</span>
          <button
            className="button button--primary"
            disabled={!input.trim() || submitting}
            type="submit"
          >
            {submitting ? "Sending..." : "Send message"}
          </button>
        </div>
      </form>
    </section>
  );
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function dateFieldLabel(inputContext: string) {
  if (inputContext === "date_of_birth") {
    return "Choose date of birth";
  }
  if (inputContext === "appointment_date") {
    return "Choose preferred appointment date";
  }
  if (inputContext === "service_date") {
    return "Choose date of service";
  }
  return "Choose a date";
}

function dateFieldMin(inputContext: string) {
  if (inputContext === "appointment_date") {
    return todayIso();
  }
  return undefined;
}

function dateFieldMax(inputContext: string) {
  if (inputContext === "date_of_birth" || inputContext === "service_date") {
    return todayIso();
  }
  return undefined;
}

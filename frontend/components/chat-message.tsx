"use client";

import type {
  AppointmentSummary,
  ClaimSummary,
  ConversationMessage
} from "../lib/types";

const amountFormatter = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "EUR"
});

function formatBool(value: boolean | null | undefined) {
  if (value === null || value === undefined) {
    return "Not provided";
  }
  return value ? "Yes" : "No";
}

function formatAmount(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "Not provided";
  }
  return amountFormatter.format(value);
}

function renderCardGrid(items: Array<{ label: string; value: string }>) {
  return (
    <div className="summary">
      {items.map((item) => (
        <div className="summary__item" key={item.label}>
          <span className="summary__label">{item.label}</span>
          <strong className="summary__value">{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

function renderClaimSummary(summary: ClaimSummary) {
  return renderCardGrid([
    { label: "Treatment", value: summary.claim_type || "Not provided" },
    { label: "Date of service", value: summary.date_of_service || "Not provided" },
    { label: "Amount", value: formatAmount(summary.amount_eur) },
    { label: "Receipt", value: formatBool(summary.has_receipt) },
    { label: "Covered", value: formatBool(summary.policy_covered) },
    { label: "Coverage source", value: summary.coverage_source || "Not provided" },
    { label: "Coverage details", value: summary.coverage_details || "Not provided" }
  ]);
}

function renderAppointmentSummary(summary: AppointmentSummary) {
  return renderCardGrid([
    { label: "Appointment type", value: summary.appointment_type || "Not provided" },
    { label: "Date of birth", value: summary.date_of_birth || "Not provided" },
    { label: "Mode", value: summary.appointment_mode || "Not provided" },
    { label: "Preferred date", value: summary.preferred_date || "Not provided" },
    {
      label: "Time window",
      value: summary.preferred_time_window || "Not provided"
    },
    { label: "Location", value: summary.location || "Not provided" },
    { label: "Covered", value: formatBool(summary.policy_covered) },
    { label: "Coverage source", value: summary.coverage_source || "Not provided" },
    { label: "Coverage details", value: summary.coverage_details || "Not provided" }
  ]);
}

export function ChatMessage({ message }: { message: ConversationMessage }) {
  const isAssistant = message.role === "assistant";

  return (
    <article className={`message message--${message.role}`}>
      <div className="message__eyebrow">{isAssistant ? "Policy assistant" : "You"}</div>
      <div className="message__body">{message.content}</div>
      {message.claimSummary ? (
        <div className="message__summary">
          <div className="message__summary-label">Claim summary</div>
          {renderClaimSummary(message.claimSummary)}
        </div>
      ) : null}
      {message.appointmentSummary ? (
        <div className="message__summary">
          <div className="message__summary-label">Appointment request</div>
          {renderAppointmentSummary(message.appointmentSummary)}
        </div>
      ) : null}
      {message.citation || message.disclaimer ? (
        <div className="message__meta">
          {message.citation ? (
            <div className="meta-card">
              <span>Source</span>
              <p>{message.citation}</p>
            </div>
          ) : null}
          {message.disclaimer ? (
            <div className="meta-card">
              <span>Note</span>
              <p>{message.disclaimer}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

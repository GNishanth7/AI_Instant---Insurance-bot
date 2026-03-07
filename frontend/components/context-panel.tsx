"use client";

import type {
  AppointmentSummary,
  ClaimSummary,
  PlanDetail,
  SourceItem
} from "../lib/types";

export type ContextView = "overview" | "sources" | "workflow";

interface ContextPanelProps {
  activeView: ContextView;
  appointmentSummary: AppointmentSummary | null;
  claimSummary: ClaimSummary | null;
  latestSources: SourceItem[];
  selectedPlan: PlanDetail | null;
  onViewChange: (view: ContextView) => void;
}

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
  return `EUR ${value.toFixed(2)}`;
}

export function ContextPanel({
  activeView,
  appointmentSummary,
  claimSummary,
  latestSources,
  selectedPlan,
  onViewChange
}: ContextPanelProps) {
  return (
    <aside className="context-panel card">
      <div className="panel-heading panel-heading--compact">
        <div>
          <span className="eyebrow eyebrow--dark">Context</span>
          <h2>Supporting details</h2>
        </div>
      </div>

      <div className="tab-row">
        <button
          className={`tab ${activeView === "overview" ? "tab--active" : ""}`}
          onClick={() => onViewChange("overview")}
          type="button"
        >
          Overview
        </button>
        <button
          className={`tab ${activeView === "sources" ? "tab--active" : ""}`}
          onClick={() => onViewChange("sources")}
          type="button"
        >
          Sources
        </button>
        <button
          className={`tab ${activeView === "workflow" ? "tab--active" : ""}`}
          onClick={() => onViewChange("workflow")}
          type="button"
        >
          Workflow
        </button>
      </div>

      {activeView === "overview" ? (
        <div className="context-stack">
          <section className="detail-card">
            <span className="section-label">Current plan</span>
            <h3>{selectedPlan?.display_name ?? "No plan selected"}</h3>
            <p>
              Keep the main conversation clean. This panel carries the supporting policy and
              workflow context, so the chat stays readable.
            </p>
          </section>

          <section className="detail-card">
            <span className="section-label">Plan summary</span>
            <div className="metric-grid metric-grid--compact">
              <article className="metric-card">
                <span>Benefits</span>
                <strong>{selectedPlan?.benefit_count ?? "--"}</strong>
              </article>
              <article className="metric-card">
                <span>Categories</span>
                <strong>{selectedPlan?.category_count ?? "--"}</strong>
              </article>
              <article className="metric-card">
                <span>Sections</span>
                <strong>{selectedPlan?.section_count ?? "--"}</strong>
              </article>
            </div>
          </section>

          <section className="detail-card">
            <span className="section-label">Engine state</span>
            <dl className="data-list">
              <div>
                <dt>Retrieval mode</dt>
                <dd>{selectedPlan?.vector_enabled ? "Vector index" : "Keyword fallback"}</dd>
              </div>
              <div>
                <dt>Answer generation</dt>
                <dd>{selectedPlan?.ai_generation_enabled ? "Gemini enabled" : "Fallback only"}</dd>
              </div>
              <div>
                <dt>Latest sources</dt>
                <dd>{latestSources.length ? `${latestSources.length} retrieved matches` : "No sources yet"}</dd>
              </div>
            </dl>
          </section>
        </div>
      ) : null}

      {activeView === "sources" ? (
        <div className="context-stack">
          {latestSources.length ? (
            latestSources.slice(0, 5).map((source) => (
              <article className="source-card" key={`${source.citation}-${source.score}`}>
                <div className="source-card__score">{source.score.toFixed(2)}</div>
                <div className="source-card__body">
                  <strong>{source.benefit}</strong>
                  <p>{source.coverage}</p>
                  <span>{source.citation}</span>
                </div>
              </article>
            ))
          ) : (
            <div className="empty-card">
              Retrieved sources will appear here after the first answered question or workflow step.
            </div>
          )}
        </div>
      ) : null}

      {activeView === "workflow" ? (
        <div className="context-stack">
          <section className="detail-card">
            <span className="section-label">Claim draft</span>
            {claimSummary ? (
              <dl className="data-list">
                <div>
                  <dt>Treatment</dt>
                  <dd>{claimSummary.claim_type || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Date of service</dt>
                  <dd>{claimSummary.date_of_service || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Amount</dt>
                  <dd>{formatAmount(claimSummary.amount_eur)}</dd>
                </div>
                <div>
                  <dt>Receipt</dt>
                  <dd>{formatBool(claimSummary.has_receipt)}</dd>
                </div>
              </dl>
            ) : (
              <div className="empty-card">
                No claim draft yet. Start with a claim question to populate this module.
              </div>
            )}
          </section>

          <section className="detail-card">
            <span className="section-label">Appointment request</span>
            {appointmentSummary ? (
              <dl className="data-list">
                <div>
                  <dt>Appointment type</dt>
                  <dd>{appointmentSummary.appointment_type || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Mode</dt>
                  <dd>{appointmentSummary.appointment_mode || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Date</dt>
                  <dd>{appointmentSummary.preferred_date || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Location</dt>
                  <dd>{appointmentSummary.location || "Not provided"}</dd>
                </div>
              </dl>
            ) : (
              <div className="empty-card">
                No appointment request yet. Start an appointment workflow to populate this module.
              </div>
            )}
          </section>
        </div>
      ) : null}
    </aside>
  );
}

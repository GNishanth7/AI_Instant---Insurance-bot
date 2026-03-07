"use client";

import type { PlanDetail, PlanSummary } from "../lib/types";

interface WorkspaceTopbarProps {
  busy: boolean;
  plans: PlanSummary[];
  selectedPlan: PlanDetail | null;
  selectedPlanId: string;
  onPlanChange: (planId: string) => void;
  onRebuild: () => void;
  onReset: () => void;
}

export function WorkspaceTopbar({
  busy,
  plans,
  selectedPlan,
  selectedPlanId,
  onPlanChange,
  onRebuild,
  onReset
}: WorkspaceTopbarProps) {
  return (
    <header className="topbar card">
      <div className="topbar__main">
        <div className="topbar__copy">
          <span className="eyebrow eyebrow--dark">Member support workspace</span>
          <h1>Health Insurance Assistant</h1>
          <p>
            One workspace for grounded cover answers, claim drafting, and appointment requests.
            The plan context is fixed up front, then everything else happens in one place.
          </p>
        </div>

        <div className="topbar__controls">
          <label className="field">
            <span className="field__label">Selected plan</span>
            <select
              className="field__control"
              onChange={(event) => onPlanChange(event.target.value)}
              value={selectedPlanId}
            >
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.display_name}
                </option>
              ))}
            </select>
          </label>

          <div className="action-row">
            <button className="button button--secondary" onClick={onRebuild} type="button">
              Rebuild index
            </button>
            <button className="button button--ghost" onClick={onReset} type="button">
              New conversation
            </button>
          </div>
        </div>
      </div>

      <div className="metric-grid">
        <article className="metric-card">
          <span>Benefits</span>
          <strong>{selectedPlan?.benefit_count ?? "--"}</strong>
        </article>
        <article className="metric-card">
          <span>Sections</span>
          <strong>{selectedPlan?.section_count ?? "--"}</strong>
        </article>
        <article className="metric-card">
          <span>Retrieval</span>
          <strong>{selectedPlan?.vector_enabled ? "Vector" : "Keyword"}</strong>
        </article>
        <article className="metric-card">
          <span>AI generation</span>
          <strong>{selectedPlan?.ai_generation_enabled ? "Gemini" : "Fallback"}</strong>
        </article>
        <article className="metric-card metric-card--status">
          <span>Status</span>
          <strong>{busy ? "Working" : "Ready"}</strong>
        </article>
      </div>
    </header>
  );
}

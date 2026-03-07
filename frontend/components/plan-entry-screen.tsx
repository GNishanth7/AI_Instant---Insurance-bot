"use client";

import type { PlanSummary } from "../lib/types";

interface PlanEntryScreenProps {
  error: string;
  loading: boolean;
  plans: PlanSummary[];
  selectedPlanId: string;
  onContinue: () => void;
  onSelectPlan: (planId: string) => void;
}

export function PlanEntryScreen({
  error,
  loading,
  plans,
  selectedPlanId,
  onContinue,
  onSelectPlan
}: PlanEntryScreenProps) {
  return (
    <main className="entry-shell">
      <section className="entry-card card">
        <div className="entry-card__hero">
          <span className="eyebrow eyebrow--dark">Employee plan assistant</span>
          <h1>Choose your plan once, then use one clean workspace for every task.</h1>
          <p>
            Coverage questions, claims, and appointments should feel like one product, not three
            disconnected tools. Start by selecting the employee plan you want to work with.
          </p>
          <div className="pill-row">
            <span className="pill pill--soft">Grounded policy answers</span>
            <span className="pill pill--soft">Claim workflow</span>
            <span className="pill pill--soft">Appointment workflow</span>
          </div>
        </div>

        <div className="entry-card__selector">
          <div className="section-heading">
            <span className="eyebrow eyebrow--dark">Available plans</span>
            <h2>Select the right policy plan</h2>
          </div>

          <div className="plan-grid">
            {plans.map((plan) => {
              const isSelected = plan.id === selectedPlanId;
              return (
                <button
                  className={`plan-tile ${isSelected ? "plan-tile--selected" : ""}`}
                  key={plan.id}
                  onClick={() => onSelectPlan(plan.id)}
                  type="button"
                >
                  <strong>{plan.display_name}</strong>
                  <span>{plan.benefit_count} benefit rows</span>
                  <span>
                    {plan.category_count} categories, {plan.section_count} sections
                  </span>
                </button>
              );
            })}
          </div>

          {error ? <div className="banner banner--error">{error}</div> : null}

          <button
            className="button button--primary button--block"
            disabled={!selectedPlanId || loading}
            onClick={onContinue}
            type="button"
          >
            {loading ? "Loading plan..." : "Continue to workspace"}
          </button>
        </div>
      </section>
    </main>
  );
}

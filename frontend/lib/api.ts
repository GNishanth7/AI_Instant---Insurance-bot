import type { ChatResponse, PlanDetail, PlanSummary } from "./types";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {});
  if (!headers.has("Content-Type") && options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
    cache: "no-store",
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  });

  if (!response.ok) {
    const detail = await extractError(response);
    throw new ApiError(detail);
  }

  return (await response.json()) as T;
}

async function extractError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Ignore JSON parse issues and fall back to text.
  }

  return (await response.text()) || "Request failed.";
}

export const api = {
  listPlans: () => requestJson<PlanSummary[]>("/plans"),
  getPlan: (planId: string) => requestJson<PlanDetail>(`/plans/${planId}`),
  rebuildPlan: (planId: string) =>
    requestJson<{ rebuilt: boolean; vector_enabled: boolean }>(`/plans/${planId}/rebuild`, {
      method: "POST"
    }),
  chat: (planId: string, message: string, sessionId?: string) =>
    requestJson<ChatResponse>("/chat", {
      method: "POST",
      body: {
        plan_id: planId,
        message,
        session_id: sessionId ?? null
      }
    }),
  resetSession: (sessionId: string) =>
    requestJson<{ session_id: string; reset: boolean }>(`/sessions/${sessionId}/reset`, {
      method: "POST"
    })
};

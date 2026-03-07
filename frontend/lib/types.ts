export type ChatRole = "assistant" | "user";

export interface PlanSummary {
  id: string;
  display_name: string;
  source_file: string;
  benefit_count: number;
  category_count: number;
  section_count: number;
}

export interface PlanDetail extends PlanSummary {
  vector_enabled: boolean;
  ai_generation_enabled: boolean;
}

export interface SourceItem {
  citation: string;
  benefit: string;
  coverage: string;
  score: number;
}

export interface ClaimSummary {
  claim_type: string;
  date_of_service: string;
  amount_eur: number | null;
  has_receipt: boolean | null;
  policy_covered: boolean | null;
  coverage_source: string;
  coverage_details: string;
}

export interface AppointmentSummary {
  appointment_type: string;
  date_of_birth: string;
  appointment_mode: string;
  preferred_date: string;
  preferred_time_window: string;
  location: string;
  policy_covered: boolean | null;
  coverage_source: string;
  coverage_details: string;
}

export interface ChatResponse {
  session_id: string;
  plan_id: string;
  content: string;
  citation: string;
  sources: SourceItem[];
  claim_summary: ClaimSummary | null;
  appointment_summary: AppointmentSummary | null;
  disclaimer: string;
  quick_replies: string[];
  input_mode: string;
  input_context: string;
}

export interface ConversationMessage {
  id: string;
  role: ChatRole;
  content: string;
  citation?: string;
  sources?: SourceItem[];
  claimSummary?: ClaimSummary | null;
  appointmentSummary?: AppointmentSummary | null;
  disclaimer?: string;
  quickReplies?: string[];
  inputMode?: string;
  inputContext?: string;
}

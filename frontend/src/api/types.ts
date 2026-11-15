// Mirrors the backend Pydantic schemas (app/api/schemas.py, app/api/auth.py).

export const DOC_TYPES = [
  "medical_record",
  "medical_bill",
  "pleading",
  "correspondence",
  "discovery_request",
  "lien_notice",
  "other",
] as const;
export type DocType = (typeof DOC_TYPES)[number];

export const STATUSES = [
  "received",
  "text_extracted",
  "classified",
  "entities_extracted",
  "matched",
  "filed",
  "needs_review",
  "failed",
] as const;
export type Status = (typeof STATUSES)[number];

export interface User {
  id: string;
  email: string;
  full_name: string;
  firm_id: string;
  firm_name: string;
}

export interface DocumentSummary {
  id: string;
  original_filename: string;
  status: Status;
  doc_type: DocType | null;
  classification_confidence: number | null;
  matter_id: string | null;
  match_confidence: number | null;
  filed_name: string | null;
  review_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentEvent {
  from_status: Status | null;
  to_status: Status;
  detail: string | null;
  created_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  content_type: string;
  size_bytes: number;
  sha256: string;
  page_count: number | null;
  extracted_text: string | null;
  entities: Record<string, unknown> | null;
  filed_folder: string | null;
  assignee: string | null;
  error: string | null;
  events: DocumentEvent[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Matter {
  id: string;
  case_number: string;
  title: string;
  client_name: string;
  defendant: string | null;
}

export interface Alert {
  id: string;
  document_id: string;
  matter_id: string | null;
  kind: string;
  due_date: string;
  description: string;
  resolved: boolean;
}

export interface StatusCount {
  status: Status;
  count: number;
}

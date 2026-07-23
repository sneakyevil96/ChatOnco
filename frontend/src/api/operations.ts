import { apiRequest } from "./client";

export interface RetentionPolicySummary {
  message_content_days: number;
  tickets_and_notes_days: number;
  audit_events_days: number;
  application_logs_days: number;
  backups_days: number;
}

export interface DeliveryFailureSummary {
  message_id: string;
  ticket_id: string | null;
  ticket_reference: string | null;
  failed_at: string | null;
  error_code: string | null;
  error_summary: string | null;
}

export interface OperationalSummary {
  project_id: string;
  generated_at: string;
  pending_outbox: number;
  stale_outbox: number;
  failed_outbox: number;
  oldest_pending_at: string | null;
  unprocessed_webhook_events: number;
  delivery_failures_last_24_hours: number;
  messages_due_for_redaction: number;
  inactive_tickets_due_for_retention: number;
  last_retention_run_at: string | null;
  retention: RetentionPolicySummary;
  recent_delivery_failures: DeliveryFailureSummary[];
}

export interface AuditEvent {
  event_id: string;
  created_at: string;
  actor_account_id: string | null;
  actor_membership_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  outcome: string;
  request_id: string | null;
  metadata: Record<string, unknown>;
}

export interface AuditEventPage {
  items: AuditEvent[];
  offset: number;
  limit: number;
  total: number;
}

export function getOperationalSummary(projectId: string): Promise<OperationalSummary> {
  return apiRequest(`/api/v1/projects/${projectId}/operations/summary`);
}

export function getAuditEvents(projectId: string): Promise<AuditEventPage> {
  return apiRequest(`/api/v1/projects/${projectId}/operations/audit-events?limit=50`);
}

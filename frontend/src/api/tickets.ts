import { apiRequest } from "./client";

export type TicketStatus = "NEW" | "CLAIMED" | "WAITING_USER" | "RESOLVED" | "CLOSED";
export type TicketQueue = "new" | "mine" | "resolved" | "all";
export type DeliveryStatus = "received" | "queued" | "sent" | "delivered" | "read" | "failed";

export interface TicketAssignee {
  membership_id: string;
  email: string;
  role: "operator" | "administrator";
}

export interface TicketListItem {
  ticket_id: string;
  reference: string;
  created_at: string;
  last_activity_at: string;
  latest_message_preview: string | null;
  status: TicketStatus;
  assigned_operator: TicketAssignee | null;
  masked_phone_number: string | null;
  row_version: number;
}

export interface TicketMessage {
  message_id: string;
  ticket_id: string | null;
  direction: "inbound" | "outbound";
  sender_type: "user" | "bot" | "operator" | "system";
  message_type: "text" | "template" | "interactive" | "unsupported" | "system";
  text_content: string | null;
  attachment_metadata: Record<string, unknown> | null;
  delivery_status: DeliveryStatus;
  operator_membership_id: string | null;
  created_at: string;
  provider_timestamp: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  failed_at: string | null;
  error_code: string | null;
  error_summary: string | null;
}

export interface InternalNote {
  note_id: string;
  author_membership_id: string;
  author_email: string;
  content: string;
  created_at: string;
}

export interface TicketDetail extends TicketListItem {
  conversation_id: string;
  conversation_state: string;
  last_inbound_at: string | null;
  customer_service_window_open: boolean;
  customer_service_window_expires_at: string | null;
  reopen_until: string | null;
  messages: TicketMessage[];
  internal_notes: InternalNote[];
}

export interface OperatorNotification {
  notification_id: string;
  ticket_id: string;
  ticket_reference: string;
  notification_type: "user_replied" | "ticket_reopened" | "ticket_assigned";
  created_at: string;
  read_at: string | null;
}

export interface WhatsAppTemplate {
  template_name: string;
  language_code: string;
  purpose: string;
  approved_body_snapshot: string;
  body_parameter_count: number;
}

export function getTickets(projectId: string, queue: TicketQueue): Promise<TicketListItem[]> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets?queue=${queue}`);
}

export function getTicket(projectId: string, ticketId: string): Promise<TicketDetail> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/${ticketId}`);
}

function ticketAction(projectId: string, ticketId: string, action: string): Promise<void> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/${ticketId}/${action}`, {
    method: "POST",
  });
}

export function claimTicket(projectId: string, ticketId: string): Promise<void> {
  return ticketAction(projectId, ticketId, "claim");
}

export function releaseTicket(projectId: string, ticketId: string): Promise<void> {
  return ticketAction(projectId, ticketId, "release");
}

export function markTicketWaitingUser(projectId: string, ticketId: string): Promise<void> {
  return ticketAction(projectId, ticketId, "waiting-user");
}

export function resolveTicket(projectId: string, ticketId: string): Promise<void> {
  return ticketAction(projectId, ticketId, "resolve");
}

export function closeTicket(projectId: string, ticketId: string): Promise<void> {
  return ticketAction(projectId, ticketId, "close");
}

export function reopenTicket(projectId: string, ticketId: string): Promise<void> {
  return ticketAction(projectId, ticketId, "reopen");
}

export function reassignTicket(
  projectId: string,
  ticketId: string,
  membershipId: string,
): Promise<void> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/${ticketId}/reassign`, {
    method: "POST",
    body: JSON.stringify({ membership_id: membershipId }),
  });
}

export function replyToTicket(projectId: string, ticketId: string, text: string): Promise<TicketMessage> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/${ticketId}/reply`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function getApprovedTemplates(projectId: string): Promise<WhatsAppTemplate[]> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/templates`);
}

export function replyToTicketWithTemplate(
  projectId: string,
  ticketId: string,
  template: WhatsAppTemplate,
  bodyParameters: string[],
): Promise<TicketMessage> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/${ticketId}/reply-template`, {
    method: "POST",
    body: JSON.stringify({
      template_name: template.template_name,
      language_code: template.language_code,
      body_parameters: bodyParameters,
    }),
  });
}

export function addInternalNote(projectId: string, ticketId: string, content: string): Promise<InternalNote> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/${ticketId}/notes`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function getUnreadNotifications(projectId: string): Promise<OperatorNotification[]> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/notifications/unread`);
}

export function markNotificationRead(projectId: string, notificationId: string): Promise<void> {
  return apiRequest(`/api/v1/projects/${projectId}/tickets/notifications/${notificationId}/read`, {
    method: "POST",
  });
}

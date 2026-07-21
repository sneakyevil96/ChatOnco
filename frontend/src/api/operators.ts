import type { ProjectRole } from "./auth";
import { apiRequest } from "./client";

export interface OperatorRecord {
  account_id: string;
  membership_id: string;
  email: string;
  role: ProjectRole;
  membership_active: boolean;
  account_disabled: boolean;
  must_change_password: boolean;
}

export interface CreatedOperator extends OperatorRecord {
  temporary_password: string | null;
}

export function getOperators(projectId: string): Promise<OperatorRecord[]> {
  return apiRequest(`/api/v1/projects/${projectId}/operators`);
}

export function createOperator(
  projectId: string,
  email: string,
  role: ProjectRole,
): Promise<CreatedOperator> {
  return apiRequest(`/api/v1/projects/${projectId}/operators`, {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

export function setMembershipActive(
  projectId: string,
  accountId: string,
  isActive: boolean,
): Promise<OperatorRecord> {
  return apiRequest(`/api/v1/projects/${projectId}/operators/${accountId}/membership`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export function issuePasswordReset(
  projectId: string,
  accountId: string,
): Promise<{ reset_token: string; expires_at: string }> {
  return apiRequest(`/api/v1/projects/${projectId}/operators/${accountId}/password-reset`, {
    method: "POST",
  });
}

export function disableAccount(projectId: string, accountId: string): Promise<OperatorRecord> {
  return apiRequest(`/api/v1/projects/${projectId}/operators/${accountId}/disable`, {
    method: "POST",
  });
}

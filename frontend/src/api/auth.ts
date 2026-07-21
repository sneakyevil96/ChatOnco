import { apiRequest } from "./client";

export type ProjectRole = "operator" | "administrator";

export interface Membership {
  membership_id: string;
  project_id: "ONCODIR" | "ONCOSCREEN";
  project_name: string;
  role: ProjectRole;
}

export interface AuthenticatedUser {
  account_id: string;
  email: string;
  must_change_password: boolean;
  memberships: Membership[];
}

export function getCurrentUser(): Promise<AuthenticatedUser> {
  return apiRequest("/api/v1/auth/me");
}

export function login(email: string, password: string): Promise<AuthenticatedUser> {
  return apiRequest("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<void> {
  return apiRequest("/api/v1/auth/logout", { method: "POST" });
}

export function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  return apiRequest("/api/v1/auth/password/change", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export function completePasswordReset(
  email: string,
  resetToken: string,
  newPassword: string,
): Promise<void> {
  return apiRequest("/api/v1/auth/password/reset", {
    method: "POST",
    body: JSON.stringify({ email, reset_token: resetToken, new_password: newPassword }),
  });
}


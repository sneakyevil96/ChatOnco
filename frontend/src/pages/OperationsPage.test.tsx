import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getAuditEvents, getOperationalSummary } from "../api/operations";
import { OperationsPage } from "./OperationsPage";

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      email: "administrator@example.invalid",
      memberships: [
        {
          membership_id: "synthetic-admin-membership",
          project_id: "ONCODIR",
          project_name: "ONCODIR",
          role: "administrator",
        },
      ],
    },
    logout: vi.fn(),
  }),
}));

vi.mock("../api/operations", () => ({
  getOperationalSummary: vi.fn(),
  getAuditEvents: vi.fn(),
}));

describe("OperationsPage", () => {
  beforeEach(() => {
    vi.mocked(getOperationalSummary).mockResolvedValue({
      project_id: "ONCODIR",
      generated_at: "2026-07-23T10:00:00Z",
      pending_outbox: 1,
      stale_outbox: 0,
      failed_outbox: 2,
      oldest_pending_at: "2026-07-23T09:55:00Z",
      unprocessed_webhook_events: 0,
      delivery_failures_last_24_hours: 2,
      messages_due_for_redaction: 0,
      inactive_tickets_due_for_retention: 0,
      last_retention_run_at: "2026-07-23T02:00:00Z",
      retention: {
        message_content_days: 90,
        tickets_and_notes_days: 365,
        audit_events_days: 730,
        application_logs_days: 90,
        backups_days: 30,
      },
      recent_delivery_failures: [],
    });
    vi.mocked(getAuditEvents).mockResolvedValue({
      items: [
        {
          event_id: "synthetic-audit",
          created_at: "2026-07-23T09:00:00Z",
          actor_account_id: null,
          actor_membership_id: null,
          action: "retention.project_applied",
          target_type: "project",
          target_id: "ONCODIR",
          outcome: "success",
          request_id: null,
          metadata: {},
        },
      ],
      offset: 0,
      limit: 50,
      total: 1,
    });
  });

  it("shows project operational backlogs and audit events without message content", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/projects/ONCODIR/admin/operations"]}>
          <Routes>
            <Route path="/projects/:projectId/admin/operations" element={<OperationsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Operațiuni și audit" })).toBeInTheDocument();
    expect(screen.getByText("Trimiteri eșuate")).toBeInTheDocument();
    expect(screen.getByText("retention.project_applied")).toBeInTheDocument();
    expect(screen.queryByText("date medicale sintetice")).not.toBeInTheDocument();
  });
});

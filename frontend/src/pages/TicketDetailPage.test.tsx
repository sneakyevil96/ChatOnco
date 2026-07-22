import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getApprovedTemplates, getTicket } from "../api/tickets";
import { TicketDetailPage } from "./TicketDetailPage";

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      account_id: "synthetic-account",
      email: "operator@example.invalid",
      must_change_password: false,
      memberships: [
        {
          membership_id: "synthetic-membership",
          project_id: "ONCODIR",
          project_name: "ONCODIR",
          role: "operator",
        },
      ],
    },
    logout: vi.fn(),
  }),
}));

vi.mock("../api/tickets", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/tickets")>();
  return {
    ...original,
    getTicket: vi.fn(),
    getApprovedTemplates: vi.fn(),
    replyToTicketWithTemplate: vi.fn(),
  };
});

describe("TicketDetailPage", () => {
  beforeEach(() => {
    vi.mocked(getTicket).mockResolvedValue({
      ticket_id: "synthetic-ticket",
      reference: "ONCODIR-20260722-ABC12345",
      created_at: "2026-07-21T08:00:00Z",
      last_activity_at: "2026-07-21T08:00:00Z",
      latest_message_preview: "Întrebare sintetică",
      status: "CLAIMED",
      assigned_operator: {
        membership_id: "synthetic-membership",
        email: "operator@example.invalid",
        role: "operator",
      },
      masked_phone_number: "••••••••0123",
      row_version: 2,
      conversation_id: "synthetic-conversation",
      conversation_state: "HUMAN_ACTIVE",
      last_inbound_at: "2026-07-20T08:00:00Z",
      customer_service_window_open: false,
      customer_service_window_expires_at: "2026-07-21T08:00:00Z",
      reopen_until: null,
      messages: [],
      internal_notes: [],
    });
    vi.mocked(getApprovedTemplates).mockResolvedValue([
      {
        template_name: "synthetic_follow_up",
        language_code: "ro",
        purpose: "Continuarea conversației",
        approved_body_snapshot: "Mesaj aprobat sintetic.",
        body_parameter_count: 0,
      },
    ]);
  });

  it("offers approved templates when the free-form service window is closed", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/projects/ONCODIR/tickets/synthetic-ticket"]}>
          <Routes>
            <Route
              path="/projects/:projectId/tickets/:ticketId"
              element={<TicketDetailPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Răspuns prin șablon WhatsApp aprobat")).toBeInTheDocument();
    expect(screen.getByLabelText("Șablon aprobat")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Trimite șablonul aprobat" })).toBeDisabled();
    expect(screen.getByLabelText("Răspuns către utilizator")).toBeDisabled();
  });
});

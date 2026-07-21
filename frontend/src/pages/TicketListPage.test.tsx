import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getTickets, getUnreadNotifications } from "../api/tickets";
import { TicketListPage } from "./TicketListPage";

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
          project_name: "ONCODIR public",
          role: "operator",
        },
      ],
    },
  }),
}));

vi.mock("../api/tickets", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/tickets")>();
  return {
    ...original,
    getTickets: vi.fn(),
    getUnreadNotifications: vi.fn(),
    claimTicket: vi.fn(),
    markNotificationRead: vi.fn(),
  };
});

describe("TicketListPage", () => {
  beforeEach(() => {
    vi.mocked(getTickets).mockResolvedValue([
      {
        ticket_id: "synthetic-ticket",
        reference: "ONCODIR-20260721-ABC12345",
        created_at: "2026-07-21T10:00:00Z",
        last_activity_at: "2026-07-21T10:01:00Z",
        latest_message_preview: "Întrebare administrativă sintetică",
        status: "NEW",
        assigned_operator: null,
        masked_phone_number: "••••••••0123",
        row_version: 1,
      },
    ]);
    vi.mocked(getUnreadNotifications).mockResolvedValue([]);
  });

  it("shows the project queue without exposing a full phone number", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/projects/ONCODIR/tickets"]}>
          <Routes>
            <Route path="/projects/:projectId/tickets" element={<TicketListPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("ONCODIR-20260721-ABC12345")).toBeInTheDocument();
    expect(screen.getByText("Întrebare administrativă sintetică")).toBeInTheDocument();
    expect(screen.getByText("••••••••0123")).toBeInTheDocument();
    expect(screen.queryByText("+40700000123")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Toate active" })).not.toBeInTheDocument();
  });
});

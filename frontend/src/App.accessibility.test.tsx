import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";

vi.mock("./hooks/useAuth", () => ({
  useAuth: () => ({
    user: undefined,
    isPending: false,
    isUnauthenticated: true,
  }),
}));

describe("application accessibility foundation", () => {
  it("provides Romanian document navigation and labelled authentication controls", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/login"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("link", { name: "Sari la conținutul principal" }))
      .toHaveAttribute("href", "#main-content");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("heading", { name: "Autentificare operator" }))
      .toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "E-mail" })).toBeInTheDocument();
    expect(screen.getByLabelText("Parolă")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
  });
});

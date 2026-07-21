import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { ProjectCard } from "./ProjectCard";

describe("ProjectCard", () => {
  it("renders the configured public project name", () => {
    render(
      <MemoryRouter>
        <ProjectCard
          project={{
            project_id: "ONCODIR",
            public_name: "Nume public configurat",
            branding: { primary_color: "#245B78", logo_url: null },
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Nume public configurat" })).toBeInTheDocument();
    expect(screen.queryByText("ONCODIR / ONCOSCREEN")).not.toBeInTheDocument();
  });
});

export interface ProjectBranding {
  primary_color: string;
  logo_url: string | null;
}

export interface PublicProject {
  project_id: "ONCODIR" | "ONCOSCREEN";
  public_name: string;
  branding: ProjectBranding;
}

export async function getProjects(): Promise<PublicProject[]> {
  const response = await fetch("/api/v1/projects", {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error("Project configuration request failed");
  }

  return response.json() as Promise<PublicProject[]>;
}


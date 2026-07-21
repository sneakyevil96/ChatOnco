export interface ProjectBranding {
  primary_color: string;
  logo_url: string | null;
}

export interface PublicProject {
  project_id: "ONCODIR" | "ONCOSCREEN";
  public_name: string;
  branding: ProjectBranding;
  membership_id: string;
  role: "operator" | "administrator";
}

export async function getProjects(): Promise<PublicProject[]> {
  return apiRequest("/api/v1/projects");
}
import { apiRequest } from "./client";

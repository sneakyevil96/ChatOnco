import { Button, Card, CardActions, CardContent, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router";

import type { PublicProject } from "../api/projects";

interface ProjectCardProps {
  project: PublicProject;
}

export function ProjectCard({ project }: ProjectCardProps) {
  return (
    <Card sx={{ borderTop: `4px solid ${project.branding.primary_color}` }}>
      <CardContent>
        <Typography variant="h5" component="h2">
          {project.public_name}
        </Typography>
      </CardContent>
      <CardActions>
        <Button component={RouterLink} to={`/projects/${project.project_id}`}>
          Deschide proiectul
        </Button>
      </CardActions>
    </Card>
  );
}


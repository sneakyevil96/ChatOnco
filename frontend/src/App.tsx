import { Alert, Box, CircularProgress, Container, Stack, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes, useParams } from "react-router";

import { getProjects } from "./api/projects";
import { ProjectCard } from "./components/ProjectCard";

function ProjectList() {
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
  });

  if (projects.isPending) {
    return <CircularProgress aria-label="Se încarcă proiectele" />;
  }

  if (projects.isError) {
    return <Alert severity="error">Configurația proiectelor nu poate fi încărcată.</Alert>;
  }

  return (
    <Stack spacing={2} sx={{ width: "100%", maxWidth: 520 }}>
      {projects.data.map((project) => (
        <ProjectCard key={project.project_id} project={project} />
      ))}
    </Stack>
  );
}

function ProjectFoundation() {
  const { projectId } = useParams();
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });
  const project = projects.data?.find((item) => item.project_id === projectId);

  if (projects.isPending) {
    return <CircularProgress aria-label="Se încarcă proiectul" />;
  }

  if (!project) {
    return <Navigate to="/" replace />;
  }

  return (
    <Stack spacing={2} sx={{ width: "100%", maxWidth: 680 }}>
      <Typography variant="h3" component="h1" color="primary">
        {project.public_name}
      </Typography>
      <Alert severity="info">
        Fundația locală este activă. Autentificarea și fluxurile pentru tichete vor fi adăugate în fazele următoare.
      </Alert>
    </Stack>
  );
}

export function App() {
  return (
    <Container maxWidth="md">
      <Box component="main" className="app-shell">
        <Routes>
          <Route
            path="/"
            element={
              <Stack spacing={3} alignItems="center" sx={{ width: "100%" }}>
                <Typography variant="h4" component="h1" textAlign="center">
                  Selectați proiectul
                </Typography>
                <ProjectList />
              </Stack>
            }
          />
          <Route path="/projects/:projectId" element={<ProjectFoundation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Box>
    </Container>
  );
}


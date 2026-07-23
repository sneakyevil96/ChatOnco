import { Alert, Box, Button, CircularProgress, Container, Stack, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, Route, Routes, useParams } from "react-router";

import { getProjects } from "./api/projects";
import { ProjectCard } from "./components/ProjectCard";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { SessionHeader } from "./components/SessionHeader";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { LoginPage } from "./pages/LoginPage";
import { OperatorAdminPage } from "./pages/OperatorAdminPage";
import { OperationsPage } from "./pages/OperationsPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { TicketDetailPage } from "./pages/TicketDetailPage";
import { TicketListPage } from "./pages/TicketListPage";

function ProjectList() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });
  if (projects.isPending) return <CircularProgress aria-label="Se încarcă proiectele" />;
  if (projects.isError) return <Alert severity="error">Proiectele autorizate nu pot fi încărcate.</Alert>;
  if (projects.data.length === 0) return <Alert severity="warning">Contul nu are acces la niciun proiect.</Alert>;
  return (
    <Stack spacing={3} sx={{ width: "100%" }}>
      <SessionHeader />
      <Typography variant="h4" component="h1" textAlign="center">Selectați proiectul</Typography>
      <Stack spacing={2} sx={{ width: "100%", maxWidth: 520, alignSelf: "center" }}>
        {projects.data.map((project) => <ProjectCard key={project.project_id} project={project} />)}
      </Stack>
    </Stack>
  );
}

function ProjectFoundation() {
  const { projectId } = useParams();
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });
  const project = projects.data?.find((item) => item.project_id === projectId);
  if (projects.isPending) return <CircularProgress aria-label="Se încarcă proiectul" />;
  if (!project) return <Navigate to="/" replace />;
  return (
    <Stack spacing={3} sx={{ width: "100%", maxWidth: 760 }}>
      <SessionHeader />
      <Typography variant="h3" component="h1" sx={{ color: project.branding.primary_color }}>{project.public_name}</Typography>
      <Alert severity="info">Autentificarea, izolarea proiectului și fluxul de suport uman sunt active.</Alert>
      <Stack direction="row" spacing={2}>
        <Button component={Link} to="/">Proiecte</Button>
        <Button component={Link} variant="contained" to={`/projects/${project.project_id}/tickets`}>Tichete</Button>
        {project.role === "administrator" && (
          <>
            <Button component={Link} to={`/projects/${project.project_id}/admin/operators`}>Administrare operatori</Button>
            <Button component={Link} to={`/projects/${project.project_id}/admin/operations`}>Operațiuni și audit</Button>
          </>
        )}
      </Stack>
    </Stack>
  );
}

export function App() {
  return (
    <Container maxWidth="lg">
      <Box component="main" className="app-shell">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route path="/" element={<ProjectList />} />
            <Route path="/projects/:projectId" element={<ProjectFoundation />} />
            <Route path="/projects/:projectId/tickets" element={<TicketListPage />} />
            <Route path="/projects/:projectId/tickets/:ticketId" element={<TicketDetailPage />} />
            <Route path="/projects/:projectId/admin/operators" element={<OperatorAdminPage />} />
            <Route path="/projects/:projectId/admin/operations" element={<OperationsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Box>
    </Container>
  );
}

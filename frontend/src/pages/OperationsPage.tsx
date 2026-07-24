import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import { getAuditEvents, getOperationalSummary } from "../api/operations";
import { SessionHeader } from "../components/SessionHeader";
import { useAuth } from "../hooks/useAuth";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ro-RO", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function Metric({ label, value, warning = false }: { label: string; value: number; warning?: boolean }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, minWidth: 180, flex: 1 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="h4" color={warning && value > 0 ? "error.main" : "text.primary"}>{value}</Typography>
    </Paper>
  );
}

export function OperationsPage() {
  const { projectId = "" } = useParams();
  const auth = useAuth();
  const membership = auth.user?.memberships.find((item) => item.project_id === projectId);
  const summary = useQuery({
    queryKey: ["operations-summary", projectId],
    queryFn: () => getOperationalSummary(projectId),
    enabled: membership?.role === "administrator",
    refetchInterval: 30_000,
  });
  const audit = useQuery({
    queryKey: ["audit-events", projectId],
    queryFn: () => getAuditEvents(projectId),
    enabled: membership?.role === "administrator",
    refetchInterval: 30_000,
  });

  if (!membership || membership.role !== "administrator") return <Navigate to="/" replace />;
  if (summary.isPending || audit.isPending) return <CircularProgress aria-label="Se încarcă starea operațională" />;
  if (summary.isError || audit.isError || !summary.data || !audit.data) {
    const reason = summary.error ?? audit.error;
    return (
      <Alert severity="error">
        {reason instanceof ApiError ? reason.message : "Starea operațională nu poate fi încărcată."}
      </Alert>
    );
  }

  const data = summary.data;
  return (
    <Stack spacing={3} sx={{ width: "100%" }}>
      <SessionHeader />
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={2}>
        <div>
          <Typography variant="h4" component="h1">Operațiuni și audit</Typography>
          <Typography color="text.secondary">{projectId} · actualizat {formatDate(data.generated_at)}</Typography>
        </div>
        <Button component={Link} to={`/projects/${projectId}`}>Înapoi la proiect</Button>
      </Stack>

      <Alert severity="info">
        Valorile de retenție sunt implicite inginerești provizorii. Monitorizarea copiilor de siguranță și a infrastructurii rămâne externă aplicației.
      </Alert>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} useFlexGap flexWrap="wrap">
        <Metric label="Mesaje în așteptare" value={data.pending_outbox} />
        <Metric label="Mesaje blocate" value={data.stale_outbox} warning />
        <Metric label="Trimiteri eșuate" value={data.failed_outbox} warning />
        <Metric label="Webhook-uri neprocesate" value={data.unprocessed_webhook_events} warning />
        <Metric label="Erori în ultimele 24 h" value={data.delivery_failures_last_24_hours} warning />
      </Stack>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={1}>
          <Typography variant="h6">Retenție</Typography>
          <Typography>Ultima execuție reușită: {formatDate(data.last_retention_run_at)}</Typography>
          <Typography>Conținut mesaje: {data.retention.message_content_days} zile</Typography>
          <Typography>Tichete și note: {data.retention.tickets_and_notes_days} zile</Typography>
          <Typography>Audit: {data.retention.audit_events_days} zile</Typography>
          <Typography>Loguri aplicație: {data.retention.application_logs_days} zile</Typography>
          <Typography>Copii de siguranță: {data.retention.backups_days} zile</Typography>
          <Typography color={data.messages_due_for_redaction > 0 ? "error" : "text.secondary"}>
            Mesaje care necesită anonimizare: {data.messages_due_for_redaction}
          </Typography>
          <Typography color={data.inactive_tickets_due_for_retention > 0 ? "error" : "text.secondary"}>
            Tichete inactive care au depășit retenția: {data.inactive_tickets_due_for_retention}
          </Typography>
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>Erori recente de livrare</Typography>
        {data.recent_delivery_failures.length === 0 ? (
          <Typography color="text.secondary">Nu există erori de livrare înregistrate.</Typography>
        ) : (
          <Stack spacing={1}>
            {data.recent_delivery_failures.map((failure) => (
              <Alert key={failure.message_id} severity="error">
                {failure.ticket_id ? (
                  <Link to={`/projects/${projectId}/tickets/${failure.ticket_id}`}>
                    {failure.ticket_reference ?? "Deschide tichetul"}
                  </Link>
                ) : "Mesaj fără tichet"}
                {` · ${failure.error_code ?? "eroare"} · ${failure.error_summary ?? "fără detalii"}`}
              </Alert>
            ))}
          </Stack>
        )}
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>Evenimente de audit ({audit.data.total})</Typography>
        <TableContainer>
          <Table size="small" aria-label="Evenimente de audit">
            <TableHead>
              <TableRow>
                <TableCell>Dată</TableCell>
                <TableCell>Acțiune</TableCell>
                <TableCell>Rezultat</TableCell>
                <TableCell>Țintă</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {audit.data.items.map((event) => (
                <TableRow key={event.event_id}>
                  <TableCell>{formatDate(event.created_at)}</TableCell>
                  <TableCell>{event.action}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      color={event.outcome === "success" ? "success" : "warning"}
                      label={event.outcome}
                    />
                  </TableCell>
                  <TableCell>{event.target_type ?? "—"} {event.target_id ?? ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Stack>
  );
}

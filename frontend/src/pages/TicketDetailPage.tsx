import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useParams } from "react-router";
import { z } from "zod";

import { ApiError } from "../api/client";
import { getOperators } from "../api/operators";
import {
  addInternalNote,
  claimTicket,
  closeTicket,
  getTicket,
  markTicketWaitingUser,
  reassignTicket,
  releaseTicket,
  reopenTicket,
  replyToTicket,
  resolveTicket,
  type TicketMessage,
} from "../api/tickets";
import { DeliveryStatusChip, TicketStatusChip } from "../components/TicketStatusChip";
import { SessionHeader } from "../components/SessionHeader";
import { useAuth } from "../hooks/useAuth";

const activeStatuses = new Set(["NEW", "CLAIMED", "WAITING_USER"]);
const replySchema = z.object({ text: z.string().trim().min(1).max(4096) });
const noteSchema = z.object({ content: z.string().trim().min(1).max(10_000) });
type ReplyFields = z.infer<typeof replySchema>;
type NoteFields = z.infer<typeof noteSchema>;

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ro-RO", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function MessageCard({ message }: { message: TicketMessage }) {
  const outbound = message.direction === "outbound";
  return (
    <Box sx={{ display: "flex", justifyContent: outbound ? "flex-end" : "flex-start" }}>
      <Paper
        variant="outlined"
        sx={{
          p: 2,
          maxWidth: "80%",
          bgcolor: outbound ? "primary.50" : "background.paper",
          borderColor: message.delivery_status === "failed" ? "error.main" : "divider",
        }}
      >
        <Stack spacing={1}>
          <Typography variant="caption" color="text.secondary">
            {outbound ? "Operator" : "Utilizator"} · {formatDate(message.created_at)}
          </Typography>
          <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
            {message.text_content ?? `[${message.message_type}]`}
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <DeliveryStatusChip status={message.delivery_status} />
            {message.error_summary && (
              <Typography variant="caption" color="error">{message.error_summary}</Typography>
            )}
          </Stack>
        </Stack>
      </Paper>
    </Box>
  );
}

export function TicketDetailPage() {
  const { projectId = "", ticketId = "" } = useParams();
  const auth = useAuth();
  const membership = auth.user?.memberships.find((item) => item.project_id === projectId);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [targetMembership, setTargetMembership] = useState("");
  const replyForm = useForm<ReplyFields>({ defaultValues: { text: "" } });
  const noteForm = useForm<NoteFields>({ defaultValues: { content: "" } });
  const ticket = useQuery({
    queryKey: ["ticket", projectId, ticketId],
    queryFn: () => getTicket(projectId, ticketId),
    enabled: Boolean(membership && ticketId),
    refetchInterval: 15_000,
  });
  const operators = useQuery({
    queryKey: ["operators", projectId],
    queryFn: () => getOperators(projectId),
    enabled: membership?.role === "administrator",
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["ticket", projectId, ticketId] });
    queryClient.invalidateQueries({ queryKey: ["tickets", projectId] });
    queryClient.invalidateQueries({ queryKey: ["ticket-notifications", projectId] });
  };
  const action = useMutation({
    mutationFn: async (name: "claim" | "release" | "waiting" | "resolve" | "close" | "reopen") => {
      if (name === "claim") return claimTicket(projectId, ticketId);
      if (name === "release") return releaseTicket(projectId, ticketId);
      if (name === "waiting") return markTicketWaitingUser(projectId, ticketId);
      if (name === "resolve") return resolveTicket(projectId, ticketId);
      if (name === "close") return closeTicket(projectId, ticketId);
      return reopenTicket(projectId, ticketId);
    },
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (reason) => {
      setError(reason instanceof ApiError ? reason.message : "Acțiunea nu a putut fi efectuată.");
      refresh();
    },
  });
  const reassign = useMutation({
    mutationFn: () => reassignTicket(projectId, ticketId, targetMembership),
    onSuccess: () => {
      setNotice("Tichetul a fost reatribuit.");
      setError(null);
      refresh();
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Reatribuirea a eșuat."),
  });
  const reply = useMutation({
    mutationFn: (values: ReplyFields) => replyToTicket(projectId, ticketId, values.text),
    onSuccess: () => {
      replyForm.reset();
      setNotice("Răspunsul a fost înregistrat în coada de trimitere WhatsApp.");
      setError(null);
      refresh();
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Răspunsul nu a putut fi trimis."),
  });
  const note = useMutation({
    mutationFn: (values: NoteFields) => addInternalNote(projectId, ticketId, values.content),
    onSuccess: () => {
      noteForm.reset();
      setNotice("Nota internă a fost adăugată.");
      setError(null);
      refresh();
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Nota nu a putut fi adăugată."),
  });

  if (!membership) return <Navigate to="/" replace />;
  if (ticket.isPending) return <CircularProgress aria-label="Se încarcă tichetul" />;
  if (ticket.isError || !ticket.data) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">
          {ticket.error instanceof ApiError ? ticket.error.message : "Tichetul nu poate fi încărcat."}
        </Alert>
        <Button component={Link} to={`/projects/${projectId}/tickets`}>Înapoi la tichete</Button>
      </Stack>
    );
  }

  const detail = ticket.data;
  const isAdministrator = membership.role === "administrator";
  const isAssignedToMe = detail.assigned_operator?.membership_id === membership.membership_id;
  const isActive = activeStatuses.has(detail.status);
  const canManage = isAdministrator || isAssignedToMe;
  const canWrite = canManage;
  const availableOperators = operators.data?.filter(
    (operator) => operator.membership_active && !operator.account_disabled,
  );

  return (
    <Stack spacing={3} sx={{ width: "100%" }}>
      <SessionHeader />
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
        <div>
          <Typography variant="h4" component="h1">{detail.reference}</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
            <TicketStatusChip status={detail.status} />
            <Chip size="small" label={`Contact: ${detail.masked_phone_number ?? "necunoscut"}`} />
            <Chip
              size="small"
              color={detail.customer_service_window_open ? "success" : "error"}
              label={detail.customer_service_window_open ? "Fereastra WhatsApp deschisă" : "Fereastra WhatsApp închisă"}
            />
          </Stack>
        </div>
        <Button component={Link} to={`/projects/${projectId}/tickets`}>Înapoi la tichete</Button>
      </Stack>

      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice(null)}>{notice}</Alert>}
      {!detail.customer_service_window_open && isActive && (
        <Alert severity="warning">
          Ultimul mesaj primit depășește 24 de ore. Un răspuns liber nu poate fi trimis; va fi necesar un șablon WhatsApp aprobat.
        </Alert>
      )}

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h6">Acțiuni</Typography>
          <Typography variant="body2" color="text.secondary">
            Operator atribuit: {detail.assigned_operator?.email ?? "neatribuit"} · Ultima activitate: {formatDate(detail.last_activity_at)}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
            {detail.status === "NEW" && !detail.assigned_operator && (
              <Button variant="contained" onClick={() => action.mutate("claim")} disabled={action.isPending}>Preia</Button>
            )}
            {isActive && canManage && detail.assigned_operator && (
              <Button onClick={() => action.mutate("release")} disabled={action.isPending}>Eliberează</Button>
            )}
            {isActive && canManage && (
              <>
                <Button onClick={() => action.mutate("waiting")} disabled={action.isPending}>Așteaptă utilizatorul</Button>
                <Button color="success" onClick={() => action.mutate("resolve")} disabled={action.isPending}>Rezolvă</Button>
              </>
            )}
            {isAdministrator && detail.status !== "CLOSED" && (
              <Button color="error" onClick={() => action.mutate("close")} disabled={action.isPending}>Închide definitiv</Button>
            )}
            {isAdministrator && detail.status === "RESOLVED" && (
              <Button onClick={() => action.mutate("reopen")} disabled={action.isPending}>Redeschide</Button>
            )}
          </Stack>
          {isAdministrator && isActive && (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                select
                size="small"
                label="Reatribuie operatorului"
                value={targetMembership}
                onChange={(event) => setTargetMembership(event.target.value)}
                sx={{ minWidth: 280 }}
              >
                {availableOperators?.map((operator) => (
                  <MenuItem key={operator.membership_id} value={operator.membership_id}>
                    {operator.email} ({operator.role})
                  </MenuItem>
                ))}
              </TextField>
              <Button
                onClick={() => reassign.mutate()}
                disabled={!targetMembership || reassign.isPending}
              >
                Reatribuie
              </Button>
            </Stack>
          )}
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h6">Conversație WhatsApp</Typography>
          <Typography variant="body2" color="text.secondary">
            Ultimul mesaj primit: {formatDate(detail.last_inbound_at)} · Expirarea ferestrei: {formatDate(detail.customer_service_window_expires_at)}
          </Typography>
          <Divider />
          <Stack spacing={2}>
            {detail.messages.map((message) => <MessageCard key={message.message_id} message={message} />)}
          </Stack>
          {isActive && canManage && (
            <Stack
              component="form"
              spacing={1}
              onSubmit={replyForm.handleSubmit((values) => {
                const parsed = replySchema.safeParse(values);
                if (!parsed.success) {
                  setError("Răspunsul trebuie să conțină text.");
                  return;
                }
                reply.mutate(parsed.data);
              })}
            >
              <TextField
                label="Răspuns către utilizator"
                multiline
                minRows={3}
                {...replyForm.register("text")}
                disabled={!detail.customer_service_window_open}
              />
              <Button
                type="submit"
                variant="contained"
                disabled={reply.isPending || !detail.customer_service_window_open}
                sx={{ alignSelf: "flex-start" }}
              >
                Trimite prin WhatsApp
              </Button>
            </Stack>
          )}
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h6">Note interne</Typography>
          {detail.internal_notes.length === 0 && <Typography color="text.secondary">Nu există note interne.</Typography>}
          {detail.internal_notes.map((item) => (
            <Alert key={item.note_id} severity="warning" icon={false}>
              <Typography variant="caption">{item.author_email} · {formatDate(item.created_at)}</Typography>
              <Typography sx={{ whiteSpace: "pre-wrap" }}>{item.content}</Typography>
            </Alert>
          ))}
          {canWrite && (
            <Stack
              component="form"
              direction={{ xs: "column", sm: "row" }}
              spacing={1}
              onSubmit={noteForm.handleSubmit((values) => {
                const parsed = noteSchema.safeParse(values);
                if (!parsed.success) {
                  setError("Nota trebuie să conțină text.");
                  return;
                }
                note.mutate(parsed.data);
              })}
            >
              <TextField label="Notă internă" fullWidth {...noteForm.register("content")} />
              <Button type="submit" disabled={note.isPending}>Adaugă nota</Button>
            </Stack>
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}

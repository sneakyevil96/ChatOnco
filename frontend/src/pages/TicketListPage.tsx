import {
  Alert,
  Button,
  CircularProgress,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  claimTicket,
  getTickets,
  getUnreadNotifications,
  markNotificationRead,
  type TicketQueue,
} from "../api/tickets";
import { SessionHeader } from "../components/SessionHeader";
import { TicketStatusChip } from "../components/TicketStatusChip";
import { useAuth } from "../hooks/useAuth";

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ro-RO", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

const notificationLabels = {
  user_replied: "Utilizatorul a răspuns",
  ticket_reopened: "Tichet redeschis automat",
  ticket_assigned: "Tichet atribuit",
};

export function TicketListPage() {
  const { projectId = "" } = useParams();
  const auth = useAuth();
  const membership = auth.user?.memberships.find((item) => item.project_id === projectId);
  const [queue, setQueue] = useState<TicketQueue>("new");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const tickets = useQuery({
    queryKey: ["tickets", projectId, queue],
    queryFn: () => getTickets(projectId, queue),
    enabled: Boolean(membership),
    refetchInterval: 15_000,
  });
  const notifications = useQuery({
    queryKey: ["ticket-notifications", projectId],
    queryFn: () => getUnreadNotifications(projectId),
    enabled: Boolean(membership),
    refetchInterval: 15_000,
  });
  const claim = useMutation({
    mutationFn: (ticketId: string) => claimTicket(projectId, ticketId),
    onSuccess: (_, ticketId) => {
      queryClient.invalidateQueries({ queryKey: ["tickets", projectId] });
      navigate(`/projects/${projectId}/tickets/${ticketId}`);
    },
    onError: (reason) => {
      setError(reason instanceof ApiError ? reason.message : "Tichetul nu a putut fi preluat.");
      queryClient.invalidateQueries({ queryKey: ["tickets", projectId] });
    },
  });
  const readNotification = useMutation({
    mutationFn: (notificationId: string) => markNotificationRead(projectId, notificationId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ticket-notifications", projectId] }),
  });

  if (!membership) return <Navigate to="/" replace />;

  return (
    <Stack spacing={3} sx={{ width: "100%" }}>
      <SessionHeader />
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={2}>
        <div>
          <Typography variant="h4" component="h1">Tichete — {membership.project_name}</Typography>
          <Typography color="text.secondary">Listele se actualizează automat la fiecare 15 secunde.</Typography>
        </div>
        <Button component={Link} to={`/projects/${projectId}`}>Înapoi la proiect</Button>
      </Stack>

      {notifications.data?.map((notification) => (
        <Alert
          key={notification.notification_id}
          severity="info"
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() => {
                readNotification.mutate(notification.notification_id);
                navigate(`/projects/${projectId}/tickets/${notification.ticket_id}`);
              }}
            >
              Deschide
            </Button>
          }
        >
          {notificationLabels[notification.notification_type]}: {notification.ticket_reference}
        </Alert>
      ))}
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

      <Paper>
        <Tabs
          value={queue}
          onChange={(_, value: TicketQueue) => setQueue(value)}
          variant="scrollable"
          scrollButtons="auto"
          aria-label="Cozi de tichete"
        >
          <Tab value="new" label="Tichete noi" />
          <Tab value="mine" label="Atribuite mie" />
          <Tab value="resolved" label="Rezolvate" />
          {membership.role === "administrator" && <Tab value="all" label="Toate active" />}
        </Tabs>
      </Paper>

      {tickets.isPending && <CircularProgress aria-label="Se încarcă tichetele" />}
      {tickets.isError && (
        <Alert severity="error">
          {tickets.error instanceof ApiError ? tickets.error.message : "Tichetele nu pot fi încărcate."}
        </Alert>
      )}
      {tickets.data && tickets.data.length === 0 && (
        <Alert severity="info">Nu există tichete în această listă.</Alert>
      )}
      {tickets.data && tickets.data.length > 0 && (
        <Paper sx={{ overflowX: "auto" }}>
          <Table aria-label="Lista tichetelor">
            <TableHead>
              <TableRow>
                <TableCell>Referință</TableCell>
                <TableCell>Creat</TableCell>
                <TableCell>Ultimul mesaj</TableCell>
                <TableCell>Stare</TableCell>
                <TableCell>Operator</TableCell>
                <TableCell>Contact</TableCell>
                <TableCell>Acțiuni</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tickets.data.map((ticket) => (
                <TableRow key={ticket.ticket_id} hover>
                  <TableCell>{ticket.reference}</TableCell>
                  <TableCell>{formatDate(ticket.created_at)}</TableCell>
                  <TableCell sx={{ maxWidth: 320 }}>{ticket.latest_message_preview ?? "—"}</TableCell>
                  <TableCell><TicketStatusChip status={ticket.status} /></TableCell>
                  <TableCell>{ticket.assigned_operator?.email ?? "Neatribuit"}</TableCell>
                  <TableCell>{ticket.masked_phone_number ?? "—"}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1}>
                      <Button
                        size="small"
                        component={Link}
                        to={`/projects/${projectId}/tickets/${ticket.ticket_id}`}
                      >
                        Deschide
                      </Button>
                      {ticket.status === "NEW" && !ticket.assigned_operator && (
                        <Button
                          size="small"
                          variant="contained"
                          disabled={claim.isPending}
                          onClick={() => claim.mutate(ticket.ticket_id)}
                        >
                          Preia
                        </Button>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}
    </Stack>
  );
}

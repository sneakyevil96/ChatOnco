import { Chip } from "@mui/material";

import type { DeliveryStatus, TicketStatus } from "../api/tickets";

const ticketLabels: Record<TicketStatus, string> = {
  NEW: "Nou",
  CLAIMED: "Preluat",
  WAITING_USER: "Așteaptă utilizatorul",
  RESOLVED: "Rezolvat",
  CLOSED: "Închis",
};

const ticketColors: Record<TicketStatus, "default" | "primary" | "warning" | "success"> = {
  NEW: "warning",
  CLAIMED: "primary",
  WAITING_USER: "warning",
  RESOLVED: "success",
  CLOSED: "default",
};

export function TicketStatusChip({ status }: { status: TicketStatus }) {
  return <Chip size="small" label={ticketLabels[status]} color={ticketColors[status]} />;
}

const deliveryLabels: Record<DeliveryStatus, string> = {
  received: "Primit",
  queued: "În așteptare",
  sent: "Trimis",
  delivered: "Livrat",
  read: "Citit",
  failed: "Eșuat",
};

export function DeliveryStatusChip({ status }: { status: DeliveryStatus }) {
  return (
    <Chip
      size="small"
      variant="outlined"
      color={status === "failed" ? "error" : "default"}
      label={deliveryLabels[status]}
    />
  );
}

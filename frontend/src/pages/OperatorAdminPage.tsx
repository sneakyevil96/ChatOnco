import {
  Alert,
  Button,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useParams } from "react-router";
import { z } from "zod";

import type { ProjectRole } from "../api/auth";
import { ApiError } from "../api/client";
import {
  createOperator,
  disableAccount,
  getOperators,
  issuePasswordReset,
  setMembershipActive,
} from "../api/operators";
import { SessionHeader } from "../components/SessionHeader";
import { useAuth } from "../hooks/useAuth";

const schema = z.object({
  email: z.string().email("E-mail invalid"),
  role: z.enum(["operator", "administrator"]),
});
type Fields = z.infer<typeof schema>;

export function OperatorAdminPage() {
  const { projectId = "" } = useParams();
  const auth = useAuth();
  const membership = auth.user?.memberships.find((item) => item.project_id === projectId);
  const queryClient = useQueryClient();
  const form = useForm<Fields>({ defaultValues: { role: "operator" } });
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const operators = useQuery({
    queryKey: ["operators", projectId],
    queryFn: () => getOperators(projectId),
    enabled: membership?.role === "administrator",
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["operators", projectId] });
  const createMutation = useMutation({
    mutationFn: (values: Fields) => createOperator(projectId, values.email, values.role as ProjectRole),
    onSuccess: (created) => {
      setNotice(
        created.temporary_password
          ? `Cont creat. Parola temporară (afișată o singură dată): ${created.temporary_password}`
          : "Accesul contului existent la proiect a fost adăugat.",
      );
      setError(null);
      form.reset({ email: "", role: "operator" });
      refresh();
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Crearea contului a eșuat."),
  });
  const actionMutation = useMutation({
    mutationFn: async (action: { type: "membership" | "reset" | "disable"; accountId: string; active?: boolean }) => {
      if (action.type === "membership") return setMembershipActive(projectId, action.accountId, Boolean(action.active));
      if (action.type === "disable") return disableAccount(projectId, action.accountId);
      const reset = await issuePasswordReset(projectId, action.accountId);
      setNotice(`Cod de resetare (afișat o singură dată): ${reset.reset_token}`);
      return reset;
    },
    onSuccess: refresh,
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Acțiunea a eșuat."),
  });

  if (!membership || membership.role !== "administrator") {
    return <Navigate to="/" replace />;
  }
  return (
    <Stack spacing={3} sx={{ width: "100%" }}>
      <SessionHeader />
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        spacing={2}
      >
        <Typography variant="h4" component="h1">Administrare operatori — {membership.project_name}</Typography>
        <Button component={Link} to={`/projects/${projectId}`}>Înapoi</Button>
      </Stack>
      {notice && <Alert severity="warning" onClose={() => setNotice(null)}>{notice}</Alert>}
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      <Paper sx={{ p: 3 }}>
        <Stack component="form" direction={{ xs: "column", md: "row" }} spacing={2} onSubmit={form.handleSubmit((values) => {
          const parsed = schema.safeParse(values);
          if (!parsed.success) {
            setError(parsed.error.issues[0]?.message ?? "Date invalide");
            return;
          }
          createMutation.mutate(parsed.data);
        })}>
          <TextField label="E-mail operator" type="email" {...form.register("email")} sx={{ flex: 1 }} />
          <TextField select label="Rol" {...form.register("role")} sx={{ minWidth: 180 }}>
            <MenuItem value="operator">Operator</MenuItem>
            <MenuItem value="administrator">Administrator</MenuItem>
          </TextField>
          <Button type="submit" variant="contained" disabled={createMutation.isPending}>Creează cont</Button>
        </Stack>
      </Paper>
      {operators.isError && <Alert severity="error">Lista operatorilor nu poate fi încărcată.</Alert>}
      <Paper sx={{ overflowX: "auto" }}>
        <Table aria-label="Lista operatorilor">
          <TableHead><TableRow><TableCell>E-mail</TableCell><TableCell>Rol</TableCell><TableCell>Stare</TableCell><TableCell>Acțiuni</TableCell></TableRow></TableHead>
          <TableBody>
            {operators.data?.map((operator) => (
              <TableRow key={operator.membership_id}>
                <TableCell>{operator.email}</TableCell>
                <TableCell>{operator.role}</TableCell>
                <TableCell>{operator.account_disabled ? "Cont dezactivat" : operator.membership_active ? "Activ" : "Acces dezactivat"}</TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1}>
                    <Button size="small" onClick={() => actionMutation.mutate({ type: "membership", accountId: operator.account_id, active: !operator.membership_active })}>
                      {operator.membership_active ? "Dezactivează accesul" : "Reactivează accesul"}
                    </Button>
                    <Button size="small" onClick={() => actionMutation.mutate({ type: "reset", accountId: operator.account_id })}>Resetare parolă</Button>
                    <Button size="small" color="error" disabled={operator.account_disabled} onClick={() => actionMutation.mutate({ type: "disable", accountId: operator.account_id })}>Dezactivează contul</Button>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}

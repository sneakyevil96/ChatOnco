import { Alert, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { z } from "zod";

import { changePassword } from "../api/auth";
import { ApiError } from "../api/client";

const schema = z.object({
  currentPassword: z.string().min(1),
  newPassword: z.string().min(12, "Parola trebuie să conțină cel puțin 12 caractere."),
});
type Fields = z.infer<typeof schema>;

export function ChangePasswordPage() {
  const form = useForm<Fields>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (values: Fields) => changePassword(values.currentPassword, values.newPassword),
    onSuccess: () => {
      queryClient.clear();
      navigate("/login", { replace: true });
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Parola nu a putut fi schimbată."),
  });
  return (
    <Paper sx={{ p: 4, width: "100%", maxWidth: 480 }}>
      <Stack spacing={3} component="form" onSubmit={form.handleSubmit((values) => {
        setError(null);
        const parsed = schema.safeParse(values);
        if (!parsed.success) {
          form.setError("newPassword", { message: parsed.error.issues[0]?.message });
          return;
        }
        mutation.mutate(parsed.data);
      })}>
        <Typography variant="h4" component="h1">Schimbare obligatorie a parolei</Typography>
        <Alert severity="info">După schimbare, autentificați-vă din nou cu noua parolă.</Alert>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField label="Parola temporară" type="password" autoComplete="current-password" {...form.register("currentPassword")} />
        <TextField
          label="Parola nouă"
          type="password"
          autoComplete="new-password"
          {...form.register("newPassword")}
          error={Boolean(form.formState.errors.newPassword)}
          helperText={form.formState.errors.newPassword?.message}
        />
        <Button type="submit" variant="contained" disabled={mutation.isPending}>Schimbă parola</Button>
      </Stack>
    </Paper>
  );
}


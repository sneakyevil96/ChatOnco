import { Alert, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router";
import { z } from "zod";

import { completePasswordReset } from "../api/auth";
import { ApiError } from "../api/client";

const schema = z.object({
  email: z.string().email(),
  resetToken: z.string().min(20),
  newPassword: z.string().min(12),
});
type Fields = z.infer<typeof schema>;

export function ResetPasswordPage() {
  const form = useForm<Fields>();
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const mutation = useMutation({
    mutationFn: (values: Fields) => completePasswordReset(values.email, values.resetToken, values.newPassword),
    onSuccess: () => setMessage({ kind: "success", text: "Parola a fost resetată. Vă puteți autentifica." }),
    onError: (reason) => setMessage({ kind: "error", text: reason instanceof ApiError ? reason.message : "Resetarea a eșuat." }),
  });
  return (
    <Paper sx={{ p: 4, width: "100%", maxWidth: 520 }}>
      <Stack spacing={2} component="form" onSubmit={form.handleSubmit((values) => {
        const parsed = schema.safeParse(values);
        if (!parsed.success) {
          setMessage({ kind: "error", text: "Verificați toate câmpurile." });
          return;
        }
        mutation.mutate(parsed.data);
      })}>
        <Typography variant="h4" component="h1">Resetare parolă</Typography>
        {message && <Alert severity={message.kind}>{message.text}</Alert>}
        <TextField label="E-mail" type="email" {...form.register("email")} />
        <TextField label="Cod de resetare" {...form.register("resetToken")} />
        <TextField label="Parola nouă" type="password" {...form.register("newPassword")} />
        <Button type="submit" variant="contained" disabled={mutation.isPending}>Salvează parola</Button>
        <Button component={Link} to="/login">Înapoi la autentificare</Button>
      </Stack>
    </Paper>
  );
}


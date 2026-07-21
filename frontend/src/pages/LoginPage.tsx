import { Alert, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate } from "react-router";
import { z } from "zod";

import { login } from "../api/auth";
import { ApiError } from "../api/client";
import { currentUserQueryKey, useAuth } from "../hooks/useAuth";

const schema = z.object({
  email: z.string().email("Introduceți o adresă de e-mail validă."),
  password: z.string().min(1, "Introduceți parola."),
});
type LoginFields = z.infer<typeof schema>;

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<LoginFields>();
  const mutation = useMutation({
    mutationFn: (values: LoginFields) => login(values.email, values.password),
    onSuccess: (user) => {
      queryClient.setQueryData(currentUserQueryKey, user);
      navigate(user.must_change_password ? "/change-password" : "/", { replace: true });
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Autentificarea a eșuat."),
  });

  if (auth.user) {
    return <Navigate to={auth.user.must_change_password ? "/change-password" : "/"} replace />;
  }

  return (
    <Paper component="section" sx={{ p: 4, width: "100%", maxWidth: 440 }}>
      <Stack spacing={3}>
        <Typography variant="h4" component="h1">Autentificare operator</Typography>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack
          component="form"
          spacing={2}
          onSubmit={form.handleSubmit((values) => {
            setError(null);
            const parsed = schema.safeParse(values);
            if (!parsed.success) {
              for (const issue of parsed.error.issues) {
                form.setError(issue.path[0] as keyof LoginFields, { message: issue.message });
              }
              return;
            }
            mutation.mutate(parsed.data);
          })}
        >
          <TextField
            label="E-mail"
            type="email"
            autoComplete="username"
            {...form.register("email")}
            error={Boolean(form.formState.errors.email)}
            helperText={form.formState.errors.email?.message}
          />
          <TextField
            label="Parolă"
            type="password"
            autoComplete="current-password"
            {...form.register("password")}
            error={Boolean(form.formState.errors.password)}
            helperText={form.formState.errors.password?.message}
          />
          <Button type="submit" variant="contained" disabled={mutation.isPending}>
            Autentificare
          </Button>
        </Stack>
        <Button component={Link} to="/reset-password" size="small">Finalizare resetare parolă</Button>
      </Stack>
    </Paper>
  );
}


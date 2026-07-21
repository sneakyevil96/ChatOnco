import { Button, Stack, Typography } from "@mui/material";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { logout } from "../api/auth";
import { useAuth } from "../hooks/useAuth";

export function SessionHeader() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mutation = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });
  return (
    <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={1} sx={{ width: "100%" }}>
      <Typography variant="body2">{auth.user?.email}</Typography>
      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>Deconectare</Button>
    </Stack>
  );
}


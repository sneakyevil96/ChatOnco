import { CircularProgress } from "@mui/material";
import { Navigate, Outlet, useLocation } from "react-router";

import { useAuth } from "../hooks/useAuth";

export function ProtectedRoute() {
  const auth = useAuth();
  const location = useLocation();
  if (auth.isPending) {
    return <CircularProgress aria-label="Se verifică autentificarea" />;
  }
  if (!auth.user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  if (auth.user.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}


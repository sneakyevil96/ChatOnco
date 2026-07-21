import { useQuery } from "@tanstack/react-query";

import { ApiError } from "../api/client";
import { getCurrentUser } from "../api/auth";

export const currentUserQueryKey = ["authenticated-user"] as const;

export function useAuth() {
  const query = useQuery({
    queryKey: currentUserQueryKey,
    queryFn: getCurrentUser,
    retry: false,
  });
  return {
    ...query,
    user: query.data,
    isUnauthenticated: query.error instanceof ApiError && query.error.status === 401,
  };
}


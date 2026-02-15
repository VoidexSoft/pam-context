import { useCallback, useEffect, useState } from "react";
import { AuthUser, getMe, getStoredToken, setAuthToken } from "../api/client";

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      // Step 1: Check if auth is required by hitting the health/config endpoint
      let isAuthRequired = false;
      try {
        const res = await fetch("/api/health");
        const data = await res.json();
        isAuthRequired = data.auth_required ?? false;
      } catch {
        // If can't reach server, assume no auth needed
        isAuthRequired = false;
      }

      if (cancelled) return;
      setAuthRequired(isAuthRequired);

      // Step 2: If we have a stored token, try to restore user from it
      const token = getStoredToken();
      if (!token) {
        setChecked(true);
        return;
      }

      // Optimistic: decode JWT locally for immediate UX while server validates
      try {
        const payload = JSON.parse(atob(token.split(".")[1]));
        if (!cancelled) {
          setUser({
            id: payload.sub || "",
            email: payload.email || "",
            name: payload.name || payload.email || "",
            role: payload.role || "viewer",
          });
        }
      } catch {
        // Invalid token format, clear immediately
        setAuthToken(null);
        setChecked(true);
        return;
      }

      // Server-side validation: call /api/auth/me to verify signature and get real user data
      try {
        const serverUser = await getMe();
        if (!cancelled) {
          setUser(serverUser);
        }
      } catch {
        // Server rejected the token (401, expired, tampered, etc.) — clear session
        if (!cancelled) {
          setAuthToken(null);
          setUser(null);
        }
      }

      if (!cancelled) {
        setChecked(true);
      }
    }

    init();

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback((authUser: AuthUser) => {
    setUser(authUser);
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    setUser(null);
  }, []);

  return { user, authRequired, checked, login, logout };
}

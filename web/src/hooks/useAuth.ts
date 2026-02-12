import { useCallback, useEffect, useState } from "react";
import { AuthUser, getStoredToken, setAuthToken } from "../api/client";

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    // Check if auth is required by hitting the health/config endpoint
    fetch("/api/health")
      .then((res) => res.json())
      .then((data) => {
        // If auth_required is in config, use it; otherwise default to false
        setAuthRequired(data.auth_required ?? false);
      })
      .catch(() => {
        // If can't reach server, assume no auth needed
        setAuthRequired(false);
      })
      .finally(() => setChecked(true));
  }, []);

  useEffect(() => {
    // If we have a stored token, try to restore user from it
    const token = getStoredToken();
    if (token) {
      try {
        // Decode JWT payload (simple base64 decode, no verification)
        const payload = JSON.parse(atob(token.split(".")[1]));
        setUser({
          id: payload.sub || "",
          email: payload.email || "",
          name: payload.name || payload.email || "",
          role: payload.role || "viewer",
        });
      } catch {
        // Invalid token, clear it
        setAuthToken(null);
      }
    }
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

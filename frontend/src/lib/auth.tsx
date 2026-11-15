import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, session } from "../api/client";
import type { User } from "../api/types";

interface Auth {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    session.clear();
    setUser(null);
  }, []);

  useEffect(() => {
    session.onUnauthorized(logout);
    // Restore the session from a stored token (if it's still valid).
    if (!session.getToken()) {
      setReady(true);
      return;
    }
    api
      .get<User>("/auth/me")
      .then(setUser)
      .catch(logout)
      .finally(() => setReady(true));
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token, user } = await api.login(email, password);
    session.setToken(access_token);
    setUser(user);
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, login, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth must be used inside <AuthProvider>");
  return auth;
}

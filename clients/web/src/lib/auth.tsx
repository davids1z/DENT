"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import { type AuthUser, loginApi, registerApi, getMeApi, logoutApi, hasAuthCookie, clearAuthFlag } from "./api";

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  /** True if an auth cookie exists (set by blocking script, available before hydration) */
  hasToken: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  hasToken: false,
  login: async () => {},
  register: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    // Read the hint set by the blocking script in layout.tsx <head>
    const hint = document.documentElement.dataset.auth === "1";
    setHasToken(hint);

    if (!hasAuthCookie()) {
      setIsLoading(false);
      return;
    }
    getMeApi()
      .then(setUser)
      .catch(() => {
        clearAuthFlag();
        document.documentElement.removeAttribute("data-auth");
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginApi(email, password);
    setUser(result.user);
    setHasToken(true);
    document.documentElement.dataset.auth = "1";
  }, []);

  const register = useCallback(async (email: string, password: string, fullName: string) => {
    const result = await registerApi(email, password, fullName);
    setUser(result.user);
    setHasToken(true);
    document.documentElement.dataset.auth = "1";
  }, []);

  const logout = useCallback(async () => {
    await logoutApi();
    setUser(null);
    setHasToken(false);
    document.documentElement.removeAttribute("data-auth");
    window.location.href = "/";
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, hasToken, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

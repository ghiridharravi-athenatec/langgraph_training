import { createContext, useCallback, useContext, useEffect, useState } from "react";
import api, { setAccessToken } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const applySession = useCallback((data) => {
    setAccessToken(data.access_token);
    setUser(data.user);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .post("/auth/refresh")
      .then(({ data }) => {
        if (!cancelled) applySession(data);
      })
      .catch(() => {
        if (!cancelled) {
          setAccessToken(null);
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applySession]);

  const login = useCallback(
    async (email, password) => {
      const { data } = await api.post("/auth/login", { email, password });
      applySession(data);
      return data.user;
    },
    [applySession]
  );

  const signup = useCallback(
    async (email, password) => {
      const { data } = await api.post("/auth/signup", { email, password });
      applySession(data);
      return data.user;
    },
    [applySession]
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const refreshUser = useCallback(async () => {
    const { data } = await api.get("/auth/me");
    setUser(data);
    return data;
  }, []);

  const value = {
    user,
    loading,
    isAuthenticated: !!user,
    isAdmin: user?.role === "admin",
    login,
    signup,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

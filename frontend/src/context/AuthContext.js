import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("ac_token");
    if (!token) {
      setReady(true);
      return;
    }
    api
      .get("/auth/me")
      .then((res) => setUser(res.data))
      .catch(() => localStorage.removeItem("ac_token"))
      .finally(() => setReady(true));
  }, []);

  const login = async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    localStorage.setItem("ac_token", res.data.token);
    setUser(res.data.user);
    return res.data.user;
  };

  const acceptInvite = async (token, password) => {
    const res = await api.post(`/invites/${token}/accept`, { password });
    localStorage.setItem("ac_token", res.data.token);
    setUser(res.data.user);
    return res.data.user;
  };

  const logout = () => {
    localStorage.removeItem("ac_token");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, ready, login, acceptInvite, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);

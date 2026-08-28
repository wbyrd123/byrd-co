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

  /**
   * Password step. Returns one of:
   *   { user }                          → password + no 2FA → fully signed in
   *   { requires_2fa: true, challenge_token, totp_available, email_available }
   *                                     → password succeeded, second factor required
   */
  const login = async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    if (res.data.requires_2fa) {
      return {
        requires_2fa: true,
        challenge_token: res.data.challenge_token,
        totp_available: res.data.totp_available,
        email_available: res.data.email_available,
      };
    }
    localStorage.setItem("ac_token", res.data.token);
    setUser(res.data.user);
    return { user: res.data.user };
  };

  /** Second-factor verification. Issues the real JWT on success. */
  const complete2FA = async (challenge_token, code, method = "totp") => {
    const res = await api.post("/auth/2fa/challenge", { challenge_token, code, method });
    localStorage.setItem("ac_token", res.data.token);
    setUser(res.data.user);
    return res.data.user;
  };

  const send2FAEmail = async (challenge_token) => {
    const res = await api.post("/auth/2fa/send-email-code", { challenge_token });
    return res.data; // { ok, sent_to_masked, expires_in_minutes }
  };

  const acceptInvite = async (token, password) => {
    const res = await api.post(`/invites/${token}/accept`, { password });
    localStorage.setItem("ac_token", res.data.token);
    setUser(res.data.user);
    return res.data.user;
  };

  const activateLender = async (token, password) => {
    const res = await api.post(`/lender/activate/${token}`, { password });
    localStorage.setItem("ac_token", res.data.token);
    setUser(res.data.user);
    return res.data.user;
  };

  const refreshUser = async () => {
    try {
      const res = await api.get("/auth/me");
      setUser(res.data);
      return res.data;
    } catch {
      return null;
    }
  };

  const logout = () => {
    localStorage.removeItem("ac_token");
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        ready,
        login,
        complete2FA,
        send2FAEmail,
        acceptInvite,
        activateLender,
        refreshUser,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);

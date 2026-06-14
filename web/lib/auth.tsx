'use client';

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from './api';

export interface User {
  id: string;
  email: string;
  full_name: string;
  company_name: string | null;
  role: string;
  plan: string;
  created_at: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { email: string; password: string; full_name: string; company_name?: string }) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const u = await api.getMe();
      setUser(u);
      if (typeof window !== 'undefined') {
        localStorage.setItem('user', JSON.stringify(u));
      }
    } catch {
      setUser(null);
      api.clearTokens();
    }
  }, []);

  useEffect(() => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
    if (token) {
      // Try restoring user from cache first, then refresh
      try {
        const cached = localStorage.getItem('user');
        if (cached) setUser(JSON.parse(cached));
      } catch { /* ignore */ }
      refreshUser().finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [refreshUser]);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api.login(email, password);
    api.setTokens(tokens.access_token, tokens.refresh_token);
    await refreshUser();
  }, [refreshUser]);

  const register = useCallback(async (data: { email: string; password: string; full_name: string; company_name?: string }) => {
    const tokens = await api.register(data);
    api.setTokens(tokens.access_token, tokens.refresh_token);
    await refreshUser();
  }, [refreshUser]);

  const logout = useCallback(() => {
    api.clearTokens();
    setUser(null);
    if (typeof window !== 'undefined') {
      localStorage.removeItem('user');
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}

'use client';

import React, { useState, useEffect } from 'react';
import Navbar from '@/components/Navbar';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import {
  Settings as SettingsIcon,
  User,
  Key,
  CreditCard,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Plus,
  Trash2,
  Copy,
} from 'lucide-react';

type Tab = 'profile' | 'api-keys' | 'subscription';

export default function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const [tab, setTab] = useState<Tab>('profile');
  const [fullName, setFullName] = useState(user?.full_name || '');
  const [companyName, setCompanyName] = useState(user?.company_name || '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // API Keys state
  const [apiKeys, setApiKeys] = useState<Array<{ id: string; name: string; prefix: string; created_at: string; last_used_at: string | null }>>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [keysLoading, setKeysLoading] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setFullName(user.full_name || '');
      setCompanyName(user.company_name || '');
    }
  }, [user]);

  useEffect(() => {
    if (tab === 'api-keys') {
      loadApiKeys();
    }
  }, [tab]);

  const loadApiKeys = async () => {
    setKeysLoading(true);
    try {
      const keys = await api.listApiKeys();
      setApiKeys(keys);
    } catch {
      setKeyError('Failed to load API keys');
    } finally {
      setKeysLoading(false);
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      await api.updateMe({ full_name: fullName, company_name: companyName });
      await refreshUser();
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: any) {
      setSaveError(err?.detail || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) return;
    setKeyError(null);
    try {
      const result = await api.createApiKey(newKeyName.trim());
      setNewKeyValue(result.key);
      setNewKeyName('');
      loadApiKeys();
    } catch (err: any) {
      setKeyError(err?.detail || 'Failed to create API key');
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
    { id: 'profile', label: 'Profile', icon: User },
    { id: 'api-keys', label: 'API Keys', icon: Key },
    { id: 'subscription', label: 'Subscription', icon: CreditCard },
  ];

  return (
    <ProtectedRoute>
      <div className="min-h-screen">
        <Navbar />
        <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <h1 className="text-2xl font-bold text-white flex items-center gap-3 mb-8">
            <SettingsIcon className="w-7 h-7 text-accent-500" /> Settings
          </h1>

          {/* Tabs */}
          <div className="flex gap-1 mb-8 border-b border-navy-700">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  tab === t.id
                    ? 'border-accent-500 text-accent-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <t.icon className="w-4 h-4" /> {t.label}
              </button>
            ))}
          </div>

          {/* Profile Tab */}
          {tab === 'profile' && (
            <form onSubmit={handleSaveProfile} className="card max-w-lg space-y-5">
              <h2 className="text-lg font-semibold text-white">Profile Information</h2>

              {saveError && (
                <div className="flex items-center gap-2 text-sm text-red-300">
                  <AlertCircle className="w-4 h-4" /> {saveError}
                </div>
              )}
              {saved && (
                <div className="flex items-center gap-2 text-sm text-emerald-300">
                  <CheckCircle2 className="w-4 h-4" /> Profile updated successfully
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Email</label>
                <input type="email" value={user?.email || ''} disabled className="input-field !bg-navy-900/40 !text-slate-500 cursor-not-allowed" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Full Name</label>
                <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} className="input-field" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Company</label>
                <input type="text" value={companyName} onChange={(e) => setCompanyName(e.target.value)} className="input-field" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Role</label>
                <input type="text" value={user?.role || 'user'} disabled className="input-field !bg-navy-900/40 !text-slate-500 cursor-not-allowed" />
              </div>
              <button type="submit" disabled={saving} className="btn-primary flex items-center gap-2">
                {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</> : 'Save Changes'}
              </button>
            </form>
          )}

          {/* API Keys Tab */}
          {tab === 'api-keys' && (
            <div className="space-y-6 max-w-lg">
              <div className="card">
                <h2 className="text-lg font-semibold text-white mb-4">API Keys</h2>
                <p className="text-sm text-slate-400 mb-4">
                  Use API keys to authenticate programmatic requests to the AI-Estimator API.
                </p>

                {keyError && (
                  <div className="flex items-center gap-2 text-sm text-red-300 mb-4">
                    <AlertCircle className="w-4 h-4" /> {keyError}
                  </div>
                )}

                {/* New key reveal */}
                {newKeyValue && (
                  <div className="bg-emerald-900/20 border border-emerald-800/30 rounded-lg p-4 mb-4">
                    <p className="text-sm text-emerald-300 font-medium mb-2">API Key Created</p>
                    <p className="text-xs text-slate-400 mb-2">Copy this key now — it won&apos;t be shown again.</p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 bg-navy-900 rounded px-3 py-2 text-sm text-accent-300 font-mono overflow-x-auto">
                        {newKeyValue}
                      </code>
                      <button onClick={() => copyToClipboard(newKeyValue)} className="btn-ghost p-2">
                        <Copy className="w-4 h-4" />
                      </button>
                    </div>
                    <button onClick={() => setNewKeyValue(null)} className="btn-ghost text-xs mt-2">
                      Dismiss
                    </button>
                  </div>
                )}

                {/* Create new key */}
                <div className="flex gap-2 mb-6">
                  <input
                    type="text"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    placeholder="Key name (e.g., 'Production')"
                    className="input-field flex-1"
                  />
                  <button onClick={handleCreateKey} disabled={!newKeyName.trim()} className="btn-secondary flex items-center gap-2">
                    <Plus className="w-4 h-4" /> Create
                  </button>
                </div>

                {/* Key list */}
                {keysLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-6 h-6 text-accent-500 animate-spin" />
                  </div>
                ) : apiKeys.length === 0 ? (
                  <p className="text-sm text-slate-500 text-center py-8">No API keys yet</p>
                ) : (
                  <div className="space-y-2">
                    {apiKeys.map((key) => (
                      <div key={key.id} className="flex items-center justify-between bg-navy-900/60 border border-navy-700/50 rounded-lg px-4 py-3">
                        <div>
                          <p className="text-sm text-slate-200">{key.name}</p>
                          <p className="text-xs text-slate-500 font-mono">{key.prefix}...</p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-slate-500">Created {new Date(key.created_at).toLocaleDateString()}</p>
                          {key.last_used_at && (
                            <p className="text-xs text-slate-600">Last used {new Date(key.last_used_at).toLocaleDateString()}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Subscription Tab */}
          {tab === 'subscription' && (
            <div className="card max-w-lg">
              <h2 className="text-lg font-semibold text-white mb-4">Subscription</h2>
              <div className="bg-navy-900/60 border border-navy-700/50 rounded-lg px-4 py-4 mb-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-white capitalize">{user?.plan || 'Free'} Plan</p>
                    <p className="text-sm text-slate-400">
                      {(user?.plan || 'free') === 'free' ? '5 jobs per month' : 'Unlimited jobs'}
                    </p>
                  </div>
                  <span className="badge-completed">{user?.plan || 'free'}</span>
                </div>
              </div>
              <a href="/pricing" className="btn-primary inline-block">
                Upgrade Plan
              </a>
            </div>
          )}
        </main>
      </div>
    </ProtectedRoute>
  );
}

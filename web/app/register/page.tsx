'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import Navbar from '@/components/Navbar';
import { Loader2, AlertCircle, Mail, Lock, User, Building2 } from 'lucide-react';

export default function RegisterPage() {
  const [form, setForm] = useState({ email: '', password: '', full_name: '', company_name: '' });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { register } = useAuth();
  const router = useRouter();

  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    setLoading(true);
    try {
      await register(form);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err?.detail || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <div className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-white">Create your account</h1>
            <p className="mt-2 text-slate-400">Start automating your construction takeoffs</p>
          </div>

          <div className="card">
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <div className="flex items-start gap-3 bg-red-900/20 border border-red-800/30 rounded-lg px-4 py-3">
                  <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                  <p className="text-sm text-red-300">{error}</p>
                </div>
              )}

              <div>
                <label htmlFor="full_name" className="block text-sm font-medium text-slate-300 mb-1.5">Full Name</label>
                <div className="relative">
                  <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input id="full_name" type="text" required value={form.full_name} onChange={set('full_name')} placeholder="John Smith" className="input-field !pl-10" />
                </div>
              </div>

              <div>
                <label htmlFor="company" className="block text-sm font-medium text-slate-300 mb-1.5">Company (optional)</label>
                <div className="relative">
                  <Building2 className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input id="company" type="text" value={form.company_name} onChange={set('company_name')} placeholder="Acme Construction" className="input-field !pl-10" />
                </div>
              </div>

              <div>
                <label htmlFor="email" className="block text-sm font-medium text-slate-300 mb-1.5">Email</label>
                <div className="relative">
                  <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input id="email" type="email" required value={form.email} onChange={set('email')} placeholder="you@company.com" className="input-field !pl-10" />
                </div>
              </div>

              <div>
                <label htmlFor="password" className="block text-sm font-medium text-slate-300 mb-1.5">Password</label>
                <div className="relative">
                  <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input id="password" type="password" required minLength={8} value={form.password} onChange={set('password')} placeholder="Min. 8 characters" className="input-field !pl-10" />
                </div>
              </div>

              <button type="submit" disabled={loading} className="btn-primary w-full flex items-center justify-center gap-2 py-3">
                {loading ? (<><Loader2 className="w-4 h-4 animate-spin" /> Creating account...</>) : 'Create Account'}
              </button>
            </form>
          </div>

          <p className="mt-6 text-center text-sm text-slate-500">
            Already have an account?{' '}
            <Link href="/login" className="text-accent-400 hover:text-accent-300 font-medium">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

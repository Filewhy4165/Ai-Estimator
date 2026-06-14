'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Navbar from '@/components/Navbar';
import ProtectedRoute from '@/components/ProtectedRoute';
import JobList from '@/components/JobList';
import { api, Job } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import Link from 'next/link';
import { RefreshCw, Plus, LayoutDashboard, FileText, Activity } from 'lucide-react';

export default function DashboardPage() {
  const { user } = useAuth();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listJobs(50, 0);
      setJobs(data.jobs || []);
      setTotal(data.total || 0);
    } catch (err: any) {
      setError(err?.detail || 'Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this job?')) return;
    try {
      await api.deleteJob(id);
      setJobs((prev) => prev.filter((j) => j.job_id !== id));
      setTotal((t) => t - 1);
    } catch {
      // Silently fail — user can refresh
    }
  };

  const completedJobs = jobs.filter((j) => j.status === 'completed').length;
  const runningJobs = jobs.filter((j) => j.status === 'running' || j.status === 'queued').length;

  return (
    <ProtectedRoute>
      <div className="min-h-screen">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Header */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8">
            <div>
              <h1 className="text-2xl font-bold text-white flex items-center gap-3">
                <LayoutDashboard className="w-7 h-7 text-accent-500" />
                Dashboard
              </h1>
              <p className="text-slate-400 mt-1">
                Welcome back{user?.full_name ? `, ${user.full_name}` : ''}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={fetchJobs} className="btn-ghost flex items-center gap-2 text-sm" disabled={loading}>
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <Link href="/upload" className="btn-primary flex items-center gap-2 text-sm">
                <Plus className="w-4 h-4" /> New Analysis
              </Link>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
            <div className="card flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-accent-500/10 flex items-center justify-center">
                <FileText className="w-6 h-6 text-accent-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-white">{total}</p>
                <p className="text-xs text-slate-500 uppercase tracking-wider">Total Projects</p>
              </div>
            </div>
            <div className="card flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-900/40 flex items-center justify-center">
                <FileText className="w-6 h-6 text-emerald-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-white">{completedJobs}</p>
                <p className="text-xs text-slate-500 uppercase tracking-wider">Completed</p>
              </div>
            </div>
            <div className="card flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-blue-900/40 flex items-center justify-center">
                <Activity className="w-6 h-6 text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-white">{runningJobs}</p>
                <p className="text-xs text-slate-500 uppercase tracking-wider">In Progress</p>
              </div>
            </div>
          </div>

          {/* Job List */}
          {error && (
            <div className="bg-red-900/20 border border-red-800/30 rounded-lg px-4 py-3 mb-6 text-sm text-red-300">
              {error}
            </div>
          )}
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <RefreshCw className="w-6 h-6 text-accent-500 animate-spin" />
            </div>
          ) : (
            <JobList jobs={jobs} onDelete={handleDelete} />
          )}
        </main>
      </div>
    </ProtectedRoute>
  );
}

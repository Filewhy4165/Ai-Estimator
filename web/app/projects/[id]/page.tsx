'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Navbar from '@/components/Navbar';
import ProtectedRoute from '@/components/ProtectedRoute';
import TakeoffResults from '@/components/TakeoffResults';
import CostSummary from '@/components/CostSummary';
import { api, Job, TakeoffResult } from '@/lib/api';
import {
  ArrowLeft,
  RefreshCw,
  Download,
  FileText,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  XCircle,
  Ban,
} from 'lucide-react';
import Link from 'next/link';

const statusConfig: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  queued:    { icon: Clock,       color: 'text-slate-400',   label: 'Queued' },
  running:   { icon: Loader2,     color: 'text-blue-400',    label: 'Analyzing...' },
  completed: { icon: CheckCircle2, color: 'text-emerald-400', label: 'Completed' },
  failed:    { icon: XCircle,     color: 'text-red-400',     label: 'Failed' },
  cancelled: { icon: Ban,         color: 'text-amber-400',   label: 'Cancelled' },
};

export default function ProjectPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [job, setJob] = useState<Job | null>(null);
  const [takeoff, setTakeoff] = useState<TakeoffResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const jobData = await api.getJob(id);
      setJob(jobData);
      if (jobData.status === 'completed') {
        try {
          const takeoffData = await api.getTakeoff(id);
          setTakeoff(takeoffData);
        } catch {
          // Takeoff might not be ready yet
        }
      }
    } catch (err: any) {
      setError(err?.detail || 'Failed to load project');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh for running/queued jobs
  useEffect(() => {
    if (job && (job.status === 'queued' || job.status === 'running')) {
      const interval = setInterval(async () => {
        try {
          const updated = await api.getJob(id);
          setJob(updated);
          if (updated.status === 'completed') {
            const takeoffData = await api.getTakeoff(id);
            setTakeoff(takeoffData);
          }
          if (updated.status !== 'queued' && updated.status !== 'running') {
            clearInterval(interval);
          }
        } catch { /* ignore */ }
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [job, id]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await api.exportCsv(id);
      const url = URL.createObjectURL(blob as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `takeoff-${id.slice(0, 8)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed. Please try again.');
    } finally {
      setExporting(false);
    }
  };

  if (loading) {
    return (
      <ProtectedRoute>
        <div className="min-h-screen">
          <Navbar />
          <div className="flex items-center justify-center py-32">
            <Loader2 className="w-8 h-8 text-accent-500 animate-spin" />
          </div>
        </div>
      </ProtectedRoute>
    );
  }

  if (error || !job) {
    return (
      <ProtectedRoute>
        <div className="min-h-screen">
          <Navbar />
          <div className="max-w-3xl mx-auto px-4 py-16 text-center">
            <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-white mb-2">Project Not Found</h2>
            <p className="text-slate-400 mb-6">{error || 'This project does not exist or you do not have access.'}</p>
            <Link href="/dashboard" className="btn-primary">Back to Dashboard</Link>
          </div>
        </div>
      </ProtectedRoute>
    );
  }

  const cfg = statusConfig[job.status] || statusConfig.queued;
  const StatusIcon = cfg.icon;

  return (
    <ProtectedRoute>
      <div className="min-h-screen">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Header */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8">
            <div className="flex items-center gap-4">
              <button onClick={() => router.push('/dashboard')} className="btn-ghost p-2">
                <ArrowLeft className="w-5 h-5" />
              </button>
              <div>
                <h1 className="text-2xl font-bold text-white">
                  {job.file_names?.[0] || `Project ${job.job_id.slice(0, 8)}`}
                </h1>
                <div className="flex items-center gap-3 mt-1">
                  <span className={`flex items-center gap-1.5 text-sm ${cfg.color}`}>
                    <StatusIcon className={`w-4 h-4 ${job.status === 'running' ? 'animate-spin' : ''}`} />
                    {cfg.label}
                  </span>
                  <span className="text-sm text-slate-500">
                    Created {new Date(job.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={fetchData} className="btn-ghost flex items-center gap-2 text-sm">
                <RefreshCw className="w-4 h-4" /> Refresh
              </button>
              {job.status === 'completed' && (
                <button
                  onClick={handleExport}
                  disabled={exporting}
                  className="btn-secondary flex items-center gap-2 text-sm"
                >
                  <Download className="w-4 h-4" />
                  {exporting ? 'Exporting...' : 'Export CSV'}
                </button>
              )}
            </div>
          </div>

          {/* Running status */}
          {(job.status === 'queued' || job.status === 'running') && (
            <div className="card mb-8 flex items-center gap-4">
              <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
              <div>
                <p className="font-medium text-white">
                  {job.status === 'queued' ? 'Analysis is queued' : 'Analyzing your blueprints...'}
                </p>
                <p className="text-sm text-slate-400">
                  This typically takes 2-5 minutes. The page will auto-refresh.
                </p>
              </div>
            </div>
          )}

          {/* Error */}
          {job.status === 'failed' && job.error_message && (
            <div className="card mb-8 !border-red-800/30 flex items-start gap-4">
              <AlertCircle className="w-6 h-6 text-red-400 shrink-0" />
              <div>
                <p className="font-medium text-red-300">Analysis Failed</p>
                <p className="text-sm text-slate-400 mt-1">{job.error_message}</p>
              </div>
            </div>
          )}

          {/* Results */}
          {job.status === 'completed' && takeoff && (
            <div className="space-y-8">
              {/* Cost Summary */}
              <div>
                <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                  <FileText className="w-5 h-5 text-accent-500" /> Cost Summary
                </h2>
                <CostSummary totals={takeoff.totals} />
              </div>

              {/* Takeoff Results */}
              <div>
                <h2 className="text-lg font-semibold text-white mb-4">
                  Takeoff Details
                </h2>
                <TakeoffResults data={takeoff} />
              </div>
            </div>
          )}

          {/* Completed but no takeoff data */}
          {job.status === 'completed' && !takeoff && (
            <div className="card text-center py-12">
              <FileText className="w-10 h-10 text-slate-600 mx-auto mb-3" />
              <p className="text-slate-400">Takeoff data is loading. Try refreshing the page.</p>
            </div>
          )}

          {/* File Info */}
          {job.file_names && job.file_names.length > 0 && (
            <div className="mt-8">
              <h3 className="text-sm font-medium text-slate-400 mb-3">Uploaded Files</h3>
              <div className="flex flex-wrap gap-2">
                {job.file_names.map((name) => (
                  <span key={name} className="inline-flex items-center gap-1.5 bg-navy-800 border border-navy-700/50 rounded-lg px-3 py-1.5 text-sm text-slate-300">
                    <FileText className="w-3.5 h-3.5 text-red-400" /> {name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </ProtectedRoute>
  );
}

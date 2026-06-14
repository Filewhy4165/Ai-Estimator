'use client';

import React from 'react';
import { Job } from '@/lib/api';
import { FileText, Clock, CheckCircle2, XCircle, Ban, Loader2, Trash2, Eye } from 'lucide-react';
import Link from 'next/link';

const statusConfig: Record<string, { icon: React.ElementType; badge: string; color: string }> = {
  queued:    { icon: Clock,        badge: 'badge-queued',    color: 'text-slate-400' },
  running:   { icon: Loader2,      badge: 'badge-running',   color: 'text-blue-400' },
  completed: { icon: CheckCircle2, badge: 'badge-completed', color: 'text-emerald-400' },
  failed:    { icon: XCircle,      badge: 'badge-failed',    color: 'text-red-400' },
  cancelled: { icon: Ban,          badge: 'badge-cancelled', color: 'text-amber-400' },
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export default function JobList({
  jobs,
  onDelete,
  compact = false,
}: {
  jobs: Job[];
  onDelete?: (id: string) => void;
  compact?: boolean;
}) {
  if (jobs.length === 0) {
    return (
      <div className="text-center py-16">
        <FileText className="w-12 h-12 text-navy-600 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-slate-300 mb-1">No projects yet</h3>
        <p className="text-slate-500 text-sm mb-6">Upload your first blueprint to get started</p>
        <Link href="/upload" className="btn-primary inline-block">
          Upload Blueprints
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {jobs.map((job) => {
        const cfg = statusConfig[job.status] || statusConfig.queued;
        const Icon = cfg.icon;
        const isRunning = job.status === 'running';

        return (
          <div
            key={job.job_id}
            className="card hover:border-navy-500 transition-all group"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-4 min-w-0">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${job.status === 'completed' ? 'bg-emerald-900/40' : 'bg-navy-700'}`}>
                  <Icon className={`w-5 h-5 ${cfg.color} ${isRunning ? 'animate-spin' : ''}`} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      href={`/projects/${job.job_id}`}
                      className="font-semibold text-white hover:text-accent-400 transition-colors truncate"
                    >
                      {job.file_names?.[0] || `Job ${job.job_id.slice(0, 8)}`}
                    </Link>
                    <span className={cfg.badge}>{job.status}</span>
                  </div>
                  {!compact && (
                    <div className="flex items-center gap-4 mt-1.5 text-xs text-slate-500">
                      <span>{formatDate(job.created_at)}</span>
                      {job.file_count && <span>{job.file_count} file{job.file_count !== 1 ? 's' : ''}</span>}
                      {job.trades && job.trades.length > 0 && (
                        <span className="truncate max-w-[300px]">{job.trades.join(', ')}</span>
                      )}
                    </div>
                  )}
                  {job.error_message && (
                    <p className="text-xs text-red-400 mt-1">{job.error_message}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <Link
                  href={`/projects/${job.job_id}`}
                  className="btn-ghost text-xs px-3 py-1.5 flex items-center gap-1.5"
                >
                  <Eye className="w-3.5 h-3.5" /> View
                </Link>
                {onDelete && (
                  <button
                    onClick={() => onDelete(job.job_id)}
                    className="btn-ghost text-xs px-2 py-1.5 text-red-400 hover:text-red-300 hover:bg-red-900/20"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

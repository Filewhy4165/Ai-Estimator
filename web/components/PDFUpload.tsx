'use client';

import React, { useCallback, useState } from 'react';
import { Upload, FileText, X, Loader2, AlertCircle } from 'lucide-react';

interface PDFUploadProps {
  onUpload: (files: File[], options?: { trades?: string[]; notes?: string }) => Promise<{ job_id: string; status: string }>;
}

export default function PDFUpload({ onUpload }: PDFUploadProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [result, setResult] = useState<{ job_id: string; status: string } | null>(null);

  const addFiles = useCallback((newFiles: FileList | File[]) => {
    const pdfFiles = Array.from(newFiles).filter(
      (f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
    );
    if (pdfFiles.length === 0) {
      setError('Only PDF files are supported');
      return;
    }
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name));
      return [...prev, ...pdfFiles.filter((f) => !existing.has(f.name))];
    });
    setError(null);
    setResult(null);
  }, []);

  const removeFile = (name: string) => {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);
      if (e.dataTransfer.files?.length) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles]
  );

  const handleUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setProgress(0);
    setError(null);

    // Simulate progress
    const interval = setInterval(() => {
      setProgress((p) => Math.min(p + Math.random() * 15, 90));
    }, 500);

    try {
      const res = await onUpload(files, { notes: notes || undefined });
      setProgress(100);
      setResult(res);
      setFiles([]);
      setNotes('');
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Upload failed. Please try again.');
    } finally {
      clearInterval(interval);
      setUploading(false);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="space-y-6">
      {/* Drop Zone */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        className={`relative border-2 border-dashed rounded-xl p-12 text-center transition-all duration-300 ${
          dragActive
            ? 'border-accent-500 bg-accent-500/5 scale-[1.01]'
            : 'border-navy-600 hover:border-navy-500 bg-navy-900/30'
        }`}
      >
        <input
          type="file"
          multiple
          accept=".pdf"
          onChange={(e) => e.target.files && addFiles(e.target.files)}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          disabled={uploading}
        />
        <div className="flex flex-col items-center gap-3">
          <div className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-colors ${
            dragActive ? 'bg-accent-500/20' : 'bg-navy-800'
          }`}>
            <Upload className={`w-8 h-8 ${dragActive ? 'text-accent-400' : 'text-slate-500'}`} />
          </div>
          <div>
            <p className="text-lg font-medium text-slate-200">
              {dragActive ? 'Drop your blueprints here' : 'Drag & drop blueprints here'}
            </p>
            <p className="text-sm text-slate-500 mt-1">
              or click to browse — PDF files only
            </p>
          </div>
        </div>
      </div>

      {/* File List */}
      {files.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-slate-400">
            Selected Files ({files.length})
          </h3>
          {files.map((f) => (
            <div
              key={f.name}
              className="flex items-center justify-between bg-navy-900/60 border border-navy-700/50 rounded-lg px-4 py-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <FileText className="w-5 h-5 text-red-400 shrink-0" />
                <span className="text-sm text-slate-200 truncate">{f.name}</span>
                <span className="text-xs text-slate-500 shrink-0">{formatSize(f.size)}</span>
              </div>
              <button
                onClick={() => removeFile(f.name)}
                disabled={uploading}
                className="text-slate-500 hover:text-red-400 transition-colors ml-2"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Notes */}
      {files.length > 0 && (
        <div>
          <label className="block text-sm font-medium text-slate-400 mb-2">
            Project Notes (optional)
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Add any special instructions or context for the analysis..."
            className="input-field min-h-[80px] resize-y"
            disabled={uploading}
          />
        </div>
      )}

      {/* Progress Bar */}
      {uploading && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400">Analyzing blueprints...</span>
            <span className="text-accent-400">{Math.round(progress)}%</span>
          </div>
          <div className="w-full bg-navy-800 rounded-full h-2.5 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-accent-600 to-accent-400 rounded-full transition-all duration-300 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-900/20 border border-red-800/30 rounded-lg px-4 py-3">
          <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{error}</p>
        </div>
      )}

      {/* Success */}
      {result && (
        <div className="flex items-start gap-3 bg-emerald-900/20 border border-emerald-800/30 rounded-lg px-4 py-3">
          <FileText className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-emerald-300 font-medium">Analysis started successfully!</p>
            <p className="text-xs text-emerald-400/70 mt-0.5">Job ID: {result.job_id}</p>
          </div>
        </div>
      )}

      {/* Upload Button */}
      {files.length > 0 && !uploading && (
        <button
          onClick={handleUpload}
          className="btn-primary w-full flex items-center justify-center gap-2 py-3"
        >
          <Upload className="w-5 h-5" />
          Analyze {files.length} File{files.length !== 1 ? 's' : ''}
        </button>
      )}

      {uploading && (
        <div className="flex items-center justify-center gap-2 text-slate-400">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Processing your blueprints... This may take a few minutes.</span>
        </div>
      )}
    </div>
  );
}

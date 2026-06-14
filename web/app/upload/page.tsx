'use client';

import React from 'react';
import Navbar from '@/components/Navbar';
import ProtectedRoute from '@/components/ProtectedRoute';
import PDFUpload from '@/components/PDFUpload';
import { api } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { Upload as UploadIcon } from 'lucide-react';

export default function UploadPage() {
  const router = useRouter();

  const handleUpload = async (files: File[], options?: { trades?: string[]; notes?: string }) => {
    const result = await api.analyze(files, options);
    // Navigate to the job detail page after a short delay
    setTimeout(() => {
      router.push(`/projects/${result.job_id}`);
    }, 2000);
    return result;
  };

  return (
    <ProtectedRoute>
      <div className="min-h-screen">
        <Navbar />
        <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <UploadIcon className="w-7 h-7 text-accent-500" />
              Upload Blueprints
            </h1>
            <p className="text-slate-400 mt-1">
              Upload PDF blueprints for AI-powered takeoff and cost estimation
            </p>
          </div>

          <div className="card">
            <PDFUpload onUpload={handleUpload} />
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}

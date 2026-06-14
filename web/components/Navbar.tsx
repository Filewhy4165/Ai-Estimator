'use client';

import React from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import {
  BarChart3,
  LogIn,
  LogOut,
  Menu,
  Upload,
  Settings,
  LayoutDashboard,
  X,
  HardHat,
} from 'lucide-react';

export default function Navbar() {
  const { user, logout, loading } = useAuth();
  const [mobileOpen, setMobileOpen] = React.useState(false);

  return (
    <nav className="sticky top-0 z-50 bg-navy-900/90 backdrop-blur-md border-b border-navy-700/50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-9 h-9 bg-accent-500 rounded-lg flex items-center justify-center shadow-lg shadow-accent-500/20 group-hover:shadow-accent-500/40 transition-shadow">
              <HardHat className="w-5 h-5 text-white" />
            </div>
            <span className="text-xl font-bold text-white tracking-tight">
              AI<span className="text-accent-500">-Estimator</span>
            </span>
          </Link>

          {/* Desktop Nav */}
          <div className="hidden md:flex items-center gap-1">
            {user ? (
              <>
                <Link href="/dashboard" className="btn-ghost flex items-center gap-2 text-sm">
                  <LayoutDashboard className="w-4 h-4" /> Dashboard
                </Link>
                <Link href="/upload" className="btn-ghost flex items-center gap-2 text-sm">
                  <Upload className="w-4 h-4" /> Upload
                </Link>
                <Link href="/settings" className="btn-ghost flex items-center gap-2 text-sm">
                  <Settings className="w-4 h-4" /> Settings
                </Link>
                <div className="w-px h-6 bg-navy-700 mx-2" />
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-400">
                    {user.full_name || user.email}
                  </span>
                  <button
                    onClick={logout}
                    className="btn-ghost flex items-center gap-1.5 text-sm text-slate-400 hover:text-red-400"
                  >
                    <LogOut className="w-4 h-4" /> Sign Out
                  </button>
                </div>
              </>
            ) : (
              <>
                <Link href="/pricing" className="btn-ghost text-sm flex items-center gap-1.5">
                  <BarChart3 className="w-4 h-4" /> Pricing
                </Link>
                <Link href="/login" className="btn-ghost flex items-center gap-1.5 text-sm">
                  <LogIn className="w-4 h-4" /> Sign In
                </Link>
                <Link href="/register" className="btn-primary text-sm ml-2">
                  Get Started
                </Link>
              </>
            )}
          </div>

          {/* Mobile menu toggle */}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="md:hidden p-2 text-slate-400 hover:text-white"
          >
            {mobileOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden bg-navy-900 border-b border-navy-700/50 px-4 pb-4 pt-2 space-y-1">
          {user ? (
            <>
              <Link href="/dashboard" onClick={() => setMobileOpen(false)} className="btn-ghost block w-full text-left text-sm flex items-center gap-2">
                <LayoutDashboard className="w-4 h-4" /> Dashboard
              </Link>
              <Link href="/upload" onClick={() => setMobileOpen(false)} className="btn-ghost block w-full text-left text-sm flex items-center gap-2">
                <Upload className="w-4 h-4" /> Upload
              </Link>
              <Link href="/settings" onClick={() => setMobileOpen(false)} className="btn-ghost block w-full text-left text-sm flex items-center gap-2">
                <Settings className="w-4 h-4" /> Settings
              </Link>
              <div className="pt-2 border-t border-navy-700">
                <button onClick={() => { logout(); setMobileOpen(false); }} className="btn-ghost block w-full text-left text-sm text-red-400 flex items-center gap-2">
                  <LogOut className="w-4 h-4" /> Sign Out
                </button>
              </div>
            </>
          ) : (
            <>
              <Link href="/login" onClick={() => setMobileOpen(false)} className="btn-ghost block w-full text-left text-sm">
                Sign In
              </Link>
              <Link href="/register" onClick={() => setMobileOpen(false)} className="btn-primary block text-center text-sm mt-2">
                Get Started
              </Link>
            </>
          )}
        </div>
      )}
    </nav>
  );
}

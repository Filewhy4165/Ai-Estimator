'use client';

import React from 'react';
import { CostTotals as CostTotalsType } from '@/lib/api';
import { DollarSign, TrendingUp, Receipt } from 'lucide-react';

function formatCurrency(val: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
}

export default function CostSummary({ totals }: { totals: CostTotalsType }) {
  const tradeEntries = Object.entries(totals.by_trade || {}).sort(
    ([, a], [, b]) => b - a
  );

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-900/40 flex items-center justify-center">
              <Receipt className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider">Subtotal</p>
              <p className="text-xl font-bold text-white">{formatCurrency(totals.subtotal)}</p>
            </div>
          </div>
        </div>
        <div className="card">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-900/40 flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider">Markup</p>
              <p className="text-xl font-bold text-white">{formatCurrency(totals.markup)}</p>
            </div>
          </div>
        </div>
        <div className="card !border-accent-500/30">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-accent-500/20 flex items-center justify-center">
              <DollarSign className="w-5 h-5 text-accent-400" />
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider">Total</p>
              <p className="text-xl font-bold text-accent-400">{formatCurrency(totals.total)}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Breakdown by Trade */}
      {tradeEntries.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-medium text-slate-400 mb-4">Cost Breakdown by Trade</h3>
          <div className="space-y-3">
            {tradeEntries.map(([trade, cost]) => {
              const pct = totals.subtotal > 0 ? (cost / totals.subtotal) * 100 : 0;
              return (
                <div key={trade}>
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="text-slate-300">{trade}</span>
                    <span className="font-medium text-white">{formatCurrency(cost)}</span>
                  </div>
                  <div className="w-full bg-navy-900 rounded-full h-2 overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-accent-600 to-accent-400 rounded-full transition-all duration-500"
                      style={{ width: `${Math.max(pct, 1)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

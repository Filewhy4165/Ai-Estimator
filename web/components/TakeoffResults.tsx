'use client';

import React, { useState } from 'react';
import { TakeoffResult, LineItem } from '@/lib/api';
import { ChevronDown, ChevronRight } from 'lucide-react';

function formatCurrency(val: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
}

function formatNumber(val: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(val);
}

export default function TakeoffResults({ data }: { data: TakeoffResult }) {
  const [expandedTrades, setExpandedTrades] = useState<Set<string>>(() =>
    new Set(data.trades.map((t) => t.trade))
  );

  const toggleTrade = (trade: string) => {
    setExpandedTrades((prev) => {
      const next = new Set(prev);
      if (next.has(trade)) next.delete(trade);
      else next.add(trade);
      return next;
    });
  };

  return (
    <div className="space-y-3">
      {data.trades.map((trade) => {
        const isExpanded = expandedTrades.has(trade.trade);
        return (
          <div key={trade.trade} className="card !p-0 overflow-hidden">
            {/* Trade Header */}
            <button
              onClick={() => toggleTrade(trade.trade)}
              className="w-full flex items-center justify-between px-6 py-4 hover:bg-navy-700/30 transition-colors"
            >
              <div className="flex items-center gap-3">
                {isExpanded ? (
                  <ChevronDown className="w-5 h-5 text-accent-500" />
                ) : (
                  <ChevronRight className="w-5 h-5 text-slate-500" />
                )}
                <span className="font-semibold text-white">{trade.trade}</span>
                <span className="text-xs text-slate-500">
                  {trade.items.length} item{trade.items.length !== 1 ? 's' : ''}
                </span>
              </div>
              <span className="font-semibold text-accent-400">
                {formatCurrency(trade.subtotal)}
              </span>
            </button>

            {/* Line Items */}
            {isExpanded && (
              <div className="border-t border-navy-700/50">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-navy-900/50 text-slate-400">
                        <th className="text-left px-6 py-2.5 font-medium">Description</th>
                        <th className="text-right px-4 py-2.5 font-medium">Qty</th>
                        <th className="text-left px-4 py-2.5 font-medium">Unit</th>
                        <th className="text-right px-4 py-2.5 font-medium">Unit Cost</th>
                        <th className="text-right px-6 py-2.5 font-medium">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trade.items.map((item: LineItem, idx: number) => (
                        <tr
                          key={idx}
                          className="border-t border-navy-800/50 hover:bg-navy-800/30 transition-colors"
                        >
                          <td className="px-6 py-3">
                            <div>
                              <span className="text-slate-200">{item.description}</span>
                              {item.csi_code && (
                                <span className="ml-2 text-xs text-slate-500">{item.csi_code}</span>
                              )}
                            </div>
                            {item.notes && (
                              <p className="text-xs text-slate-500 mt-0.5">{item.notes}</p>
                            )}
                          </td>
                          <td className="text-right px-4 py-3 text-slate-300">
                            {formatNumber(item.quantity)}
                          </td>
                          <td className="px-4 py-3 text-slate-400">{item.unit}</td>
                          <td className="text-right px-4 py-3 text-slate-300">
                            {formatCurrency(item.unit_cost)}
                          </td>
                          <td className="text-right px-6 py-3 font-medium text-white">
                            {formatCurrency(item.total_cost)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

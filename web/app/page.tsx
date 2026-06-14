'use client';

import Navbar from '@/components/Navbar';
import Link from 'next/link';
import {
  Upload,
  Zap,
  BarChart3,
  Shield,
  ArrowRight,
  CheckCircle2,
  HardHat,
  FileSearch,
  Calculator,
} from 'lucide-react';

const features = [
  {
    icon: FileSearch,
    title: 'AI-Powered Takeoff',
    desc: 'Upload blueprints and get automated quantity takeoffs powered by advanced computer vision and AI.',
  },
  {
    icon: Calculator,
    title: 'Instant Cost Estimates',
    desc: 'Real-time cost estimation with CSI-coded line items, trade breakdowns, and customizable markup.',
  },
  {
    icon: Zap,
    title: 'Process in Minutes',
    desc: 'What takes hours manually is done in minutes. Multi-file support for complete project packages.',
  },
  {
    icon: BarChart3,
    title: 'Trade Coverage Reports',
    desc: 'Comprehensive breakdown by trade — electrical, plumbing, HVAC, structural, and more.',
  },
  {
    icon: Shield,
    title: 'Enterprise Security',
    desc: 'Your blueprints are processed securely and never shared. SOC2-ready infrastructure.',
  },
  {
    icon: Upload,
    title: 'PDF & CSV Export',
    desc: 'Export results to CSV for your estimating software or generate professional HTML reports.',
  },
];

const plans = [
  {
    name: 'Free',
    price: '$0',
    period: '/mo',
    desc: 'Perfect for trying AI-powered takeoff',
    features: ['5 jobs per month', 'Single file uploads', 'Basic takeoff results', 'CSV export', 'Email support'],
    cta: 'Get Started Free',
    highlight: false,
  },
  {
    name: 'Pro',
    price: '$49',
    period: '/mo',
    desc: 'For professional estimators & teams',
    features: [
      'Unlimited jobs',
      'Multi-file uploads',
      'Advanced cost estimation',
      'Trade coverage reports',
      'Priority processing',
      'API access',
      'Priority support',
    ],
    cta: 'Start Pro Trial',
    highlight: true,
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    desc: 'For large firms & custom integrations',
    features: [
      'Everything in Pro',
      'Custom trade databases',
      'SSO & team management',
      'On-premise deployment',
      'Dedicated support',
      'SLA guarantee',
    ],
    cta: 'Contact Sales',
    highlight: false,
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen">
      <Navbar />

      {/* Hero Section */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-hero-pattern" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-accent-500/5 via-transparent to-transparent" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24 sm:py-32 lg:py-40">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 bg-accent-500/10 border border-accent-500/20 rounded-full px-4 py-1.5 mb-8">
              <HardHat className="w-4 h-4 text-accent-400" />
              <span className="text-sm text-accent-300 font-medium">AI-Powered Construction Estimation</span>
            </div>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-white leading-tight">
              Automated Takeoffs.{' '}
              <span className="text-accent-500">Instant Estimates.</span>
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-slate-400 max-w-2xl leading-relaxed">
              Upload your blueprints and get AI-powered quantity takeoffs and cost estimates in minutes, 
              not hours. Built for construction professionals who value accuracy and speed.
            </p>
            <div className="mt-10 flex flex-col sm:flex-row gap-4">
              <Link
                href="/register"
                className="btn-primary text-lg px-8 py-3.5 flex items-center justify-center gap-2"
              >
                Start Free Trial <ArrowRight className="w-5 h-5" />
              </Link>
              <Link
                href="/pricing"
                className="btn-secondary text-lg px-8 py-3.5 flex items-center justify-center gap-2"
              >
                View Pricing
              </Link>
            </div>
            <p className="mt-4 text-sm text-slate-500">
              No credit card required · 5 free jobs/month · Cancel anytime
            </p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="bg-navy-900/50 py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-white">
              Everything you need for faster estimates
            </h2>
            <p className="mt-4 text-lg text-slate-400 max-w-2xl mx-auto">
              From blueprint upload to final cost breakdown — AI-Estimator handles the heavy lifting.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((feat) => (
              <div key={feat.title} className="card hover:border-accent-500/30 transition-all group">
                <div className="w-12 h-12 rounded-xl bg-accent-500/10 flex items-center justify-center mb-4 group-hover:bg-accent-500/20 transition-colors">
                  <feat.icon className="w-6 h-6 text-accent-400" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{feat.title}</h3>
                <p className="text-slate-400 text-sm leading-relaxed">{feat.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-white">How it works</h2>
            <p className="mt-4 text-lg text-slate-400">Three steps from blueprint to estimate</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              { step: '01', title: 'Upload Blueprints', desc: 'Drag and drop your PDF blueprints. Support for multi-file project packages.' },
              { step: '02', title: 'AI Analysis', desc: 'Our AI engine analyzes every page, detecting dimensions, materials, and quantities.' },
              { step: '03', title: 'Get Results', desc: 'Review takeoff results with trade breakdowns, cost estimates, and export options.' },
            ].map((s) => (
              <div key={s.step} className="text-center">
                <div className="w-16 h-16 rounded-2xl bg-accent-500/10 border border-accent-500/20 flex items-center justify-center mx-auto mb-6">
                  <span className="text-2xl font-bold text-accent-400">{s.step}</span>
                </div>
                <h3 className="text-xl font-semibold text-white mb-2">{s.title}</h3>
                <p className="text-slate-400">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="bg-navy-900/50 py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-white">Simple, transparent pricing</h2>
            <p className="mt-4 text-lg text-slate-400">Start free, upgrade when you need more</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={`card relative ${
                  plan.highlight
                    ? '!border-accent-500/50 shadow-accent-500/10 shadow-2xl'
                    : ''
                }`}
              >
                {plan.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-accent-500 text-white text-xs font-bold px-4 py-1 rounded-full">
                    Most Popular
                  </div>
                )}
                <h3 className="text-xl font-bold text-white">{plan.name}</h3>
                <div className="mt-4 flex items-baseline gap-1">
                  <span className="text-4xl font-bold text-white">{plan.price}</span>
                  <span className="text-slate-500">{plan.period}</span>
                </div>
                <p className="mt-2 text-sm text-slate-400">{plan.desc}</p>
                <ul className="mt-6 space-y-3">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm">
                      <CheckCircle2 className="w-4 h-4 text-accent-500 shrink-0 mt-0.5" />
                      <span className="text-slate-300">{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href={plan.name === 'Enterprise' ? '/register' : '/register'}
                  className={`mt-8 block text-center py-2.5 rounded-lg font-semibold text-sm transition-all ${
                    plan.highlight
                      ? 'btn-primary'
                      : 'btn-secondary'
                  }`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
            Ready to automate your takeoffs?
          </h2>
          <p className="text-lg text-slate-400 mb-8">
            Join hundreds of construction professionals saving hours on every estimate.
          </p>
          <Link href="/register" className="btn-primary text-lg px-10 py-3.5 inline-flex items-center gap-2">
            Get Started Free <ArrowRight className="w-5 h-5" />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-navy-800 py-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <HardHat className="w-5 h-5 text-accent-500" />
              <span className="text-sm text-slate-500">
                © {new Date().getFullYear()} AI-Estimator. All rights reserved.
              </span>
            </div>
            <div className="flex items-center gap-6 text-sm text-slate-500">
              <Link href="/pricing" className="hover:text-slate-300 transition-colors">Pricing</Link>
              <Link href="/login" className="hover:text-slate-300 transition-colors">Sign In</Link>
              <Link href="/register" className="hover:text-slate-300 transition-colors">Register</Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

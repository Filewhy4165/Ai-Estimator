'use client';

import Navbar from '@/components/Navbar';
import Link from 'next/link';
import { CheckCircle2, Zap, Shield, ArrowRight } from 'lucide-react';

const plans = [
  {
    name: 'Free',
    price: '$0',
    period: '/mo',
    desc: 'Perfect for trying AI-powered takeoff',
    features: [
      '5 jobs per month',
      'Single file uploads',
      'Basic takeoff results',
      'CSV export',
      'Email support',
    ],
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
      'Dedicated account manager',
      'SLA guarantee',
    ],
    cta: 'Contact Sales',
    highlight: false,
  },
];

const faqs = [
  {
    q: 'How accurate are the AI takeoffs?',
    a: 'Our AI achieves 90%+ accuracy on standard construction documents. Results include confidence scores and can be reviewed and adjusted before export.',
  },
  {
    q: 'What file formats are supported?',
    a: 'We support PDF blueprints. Multi-page and multi-file project packages are supported on Pro and Enterprise plans.',
  },
  {
    q: 'How long does an analysis take?',
    a: 'Most analyses complete in 2-5 minutes depending on the number of pages and complexity. Pro users get priority processing.',
  },
  {
    q: 'Can I cancel my subscription?',
    a: 'Yes, you can cancel anytime. You\'ll keep access until the end of your billing period. No cancellation fees.',
  },
  {
    q: 'Is my data secure?',
    a: 'All blueprints are encrypted in transit and at rest. We never share your documents with third parties. Enterprise plans include on-premise deployment options.',
  },
];

export default function PricingPage() {
  return (
    <div className="min-h-screen">
      <Navbar />

      <section className="py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h1 className="text-4xl sm:text-5xl font-bold text-white">
              Simple, transparent pricing
            </h1>
            <p className="mt-4 text-lg text-slate-400 max-w-2xl mx-auto">
              Start free and scale as you grow. No hidden fees, no surprises.
            </p>
          </div>

          {/* Plans */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={`card relative ${
                  plan.highlight ? '!border-accent-500/50 shadow-accent-500/10 shadow-2xl' : ''
                }`}
              >
                {plan.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-accent-500 text-white text-xs font-bold px-4 py-1 rounded-full flex items-center gap-1">
                    <Zap className="w-3 h-3" /> Most Popular
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
                  href="/register"
                  className={`mt-8 block text-center py-2.5 rounded-lg font-semibold text-sm transition-all ${
                    plan.highlight ? 'btn-primary' : 'btn-secondary'
                  }`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>

          {/* Enterprise callout */}
          <div className="mt-16 card max-w-4xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-accent-500/10 flex items-center justify-center shrink-0">
                <Shield className="w-6 h-6 text-accent-400" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-white">Need a custom solution?</h3>
                <p className="text-slate-400 text-sm">On-premise deployment, custom integrations, and dedicated support.</p>
              </div>
            </div>
            <Link href="/register" className="btn-secondary flex items-center gap-2 shrink-0">
              Contact Sales <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {/* FAQ */}
          <div className="mt-24 max-w-3xl mx-auto">
            <h2 className="text-2xl font-bold text-white text-center mb-12">Frequently Asked Questions</h2>
            <div className="space-y-6">
              {faqs.map((faq) => (
                <div key={faq.q} className="card">
                  <h3 className="font-semibold text-white mb-2">{faq.q}</h3>
                  <p className="text-slate-400 text-sm leading-relaxed">{faq.a}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

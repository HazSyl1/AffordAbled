import { ArrowLeft, ArrowRight, Bell, Gauge, Mail, Pause, Play, QrCode, Users } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';

interface Slide {
  id: string;
  badge: string;
  title: string;
  description: string;
  points: string[];
  visual: ReactNode;
}

function EmailPreview() {
  return (
    <div className='mx-auto w-full max-w-xs overflow-hidden rounded-2xl bg-white text-left text-gray-800 shadow-2xl shadow-black/40' aria-hidden='true'>
      <div className='flex items-center gap-2 bg-[#a855f7] px-4 py-3 text-sm font-bold text-white'>
        <span className='flex h-7 w-7 items-center justify-center rounded-lg bg-white/20'><Mail className='h-4 w-4' /></span> AffordAbled
      </div>
      <div className='space-y-3 p-4'>
        <p className='text-xs text-gray-500'>Isha, Sarthak sent you a payment request.</p>
        <div className='rounded-xl bg-purple-50 py-3 text-center'>
          <p className='text-[10px] font-bold uppercase tracking-wider text-gray-500'>Amount requested</p>
          <p className='text-3xl font-extrabold text-purple-900'>₹500.00</p>
        </div>
        <div className='rounded-lg bg-[#a855f7] py-2 text-center text-sm font-bold text-white'>Pay with UPI</div>
        <div className='flex items-center justify-center gap-3'>
          <QrCode className='h-16 w-16 text-gray-900' />
          <p className='text-[11px] leading-4 text-gray-500'>Or scan with any UPI app</p>
        </div>
      </div>
    </div>
  );
}

function UsagePreview() {
  const rows = [['Chat messages', 18, 50], ['AI-created transactions', 6, 20]] as const;
  return (
    <div className='mx-auto w-full max-w-xs space-y-3 rounded-2xl border border-white/10 bg-[#111114] p-5' aria-hidden='true'>
      <div className='flex items-center justify-between'>
        <span className='text-xs font-semibold uppercase tracking-wider text-purple-300'>Free plan</span>
        <span className='rounded-full bg-emerald-400/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300'>Resets daily</span>
      </div>
      {rows.map(([label, used, limit]) => (
        <div key={label}>
          <div className='flex justify-between text-xs text-[var(--text-secondary)]'><span>{label}</span><span>{used} / {limit}</span></div>
          <div className='mt-1.5 h-2 overflow-hidden rounded-full bg-white/10'>
            <div className='h-full rounded-full bg-gradient-to-r from-purple-400 to-blue-400' style={{ width: `${(used / limit) * 100}%` }} />
          </div>
        </div>
      ))}
      <p className='rounded-lg bg-purple-400/10 px-3 py-2 text-[11px] text-purple-200'>Subscribers get 250 chats and 100 AI transactions a day.</p>
    </div>
  );
}

function ReminderPreview() {
  return (
    <div className='mx-auto w-full max-w-xs space-y-2 rounded-2xl border border-white/10 bg-[#111114] p-5' aria-hidden='true'>
      <p className='text-xs font-semibold uppercase tracking-wider text-purple-300'>Dinner · ₹1,200</p>
      {['Isha · ₹300', 'Piyush · ₹300', 'Dev · ₹300'].map((row, index) => (
        <div key={row} className='flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm'>
          <span>{row}</span>
          <span className={`flex items-center gap-1 text-[11px] font-semibold ${index === 0 ? 'text-emerald-300' : 'text-amber-300'}`}>
            <Bell className='h-3 w-3' /> {index === 0 ? 'Sent' : 'Queued'}
          </span>
        </div>
      ))}
      <p className='pt-1 text-[11px] text-[var(--text-muted)]'>One confirmation sends a separate email to everyone who still owes.</p>
    </div>
  );
}

const slides: Slide[] = [
  {
    id: 'reminders',
    badge: 'New · Payment reminders',
    title: 'Branded UPI reminders, in one tap',
    description: 'Ask everyone who owes you for their share with a polished email that carries the amount, a Pay with UPI button, and a scannable QR code.',
    points: ['Separate email for each person, one confirmation', 'QR is generated on our server, never an outside service', 'Cooldowns and limits keep reminders from becoming spam'],
    visual: <EmailPreview />,
  },
  {
    id: 'split-reminders',
    badge: 'New · Split-wide campaigns',
    title: 'Remind a whole split at once',
    description: 'Review who is unpaid, add any missing email addresses, and send once. The reminder count and cooldown are tracked per split, not per person.',
    points: ['See Sent, Queued, or Failed for every recipient', 'Changed amounts cancel stale reminders automatically', 'Safe to retry; nobody is emailed twice'],
    visual: <ReminderPreview />,
  },
  {
    id: 'plans',
    badge: 'New · Plans & daily usage',
    title: 'Know exactly what you have left today',
    description: 'Every account has a plan with a fair daily allowance for AI chat and AI-created transactions, shown on your Profile page.',
    points: ['Free: 50 chat messages and 20 AI transactions a day', 'Subscribed plans unlock far higher allowances', 'Clear messages with the exact reset time when you hit a limit'],
    visual: <UsagePreview />,
  },
  {
    id: 'settlement',
    badge: 'Group money',
    title: 'Settle group trips with exact math',
    description: 'Combine bills, coupons, fees, and tips into one plan and see who owes whom, checked to the paisa before anything is saved.',
    points: ['Preview never touches your wallet', 'Only your own payments create transactions', 'Chat can prepare a draft for you to review'],
    visual: (
      <div className='mx-auto flex w-full max-w-xs flex-col items-center gap-3 rounded-2xl border border-white/10 bg-[#111114] p-6' aria-hidden='true'>
        <Users className='h-9 w-9 text-purple-300' />
        <p className='text-sm font-semibold'>Dev pays Isha ₹1,150</p>
        <p className='text-sm font-semibold'>Piyush pays Isha ₹900</p>
        <p className='rounded-full bg-emerald-400/10 px-3 py-1 text-[11px] font-semibold text-emerald-300'>Totals match to the paisa</p>
      </div>
    ),
  },
];

const ROTATE_MS = 6000;

export function FeatureCarousel() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(true);
  const count = slides.length;

  useEffect(() => {
    const reduceMotion = typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (paused || reduceMotion) return undefined;
    const timer = window.setInterval(() => setIndex((current) => (current + 1) % count), ROTATE_MS);
    return () => window.clearInterval(timer);
  }, [paused, count]);

  const slide = slides[index];
  const go = (next: number) => setIndex((next + count) % count);

  return (
    <section
      id='whats-new' aria-roledescription='carousel' aria-label='What is new in AffordAbled'
      className='relative border-y border-white/[0.06] bg-gradient-to-b from-purple-500/[0.06] to-transparent'
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
    >
      <div className='mx-auto max-w-7xl px-5 py-16 sm:px-8 lg:px-10 lg:py-20'>
        <div className='flex items-end justify-between gap-4'>
          <div>
            <p className='text-xs font-semibold uppercase tracking-[0.18em] text-[var(--brand-primary)]'>What’s new</p>
            <h2 className='mt-3 text-3xl font-bold tracking-tight sm:text-4xl'>Fresh in your wallet.</h2>
          </div>
          <div className='flex items-center gap-2'>
            <button type='button' aria-label={paused ? 'Resume automatic rotation' : 'Pause automatic rotation'}
              onClick={() => setPaused((value) => !value)}
              className='flex h-10 w-10 items-center justify-center rounded-full border border-white/10 text-[var(--text-secondary)] hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'>
              {paused ? <Play className='h-4 w-4' aria-hidden='true' /> : <Pause className='h-4 w-4' aria-hidden='true' />}
            </button>
            <button type='button' aria-label='Previous feature' onClick={() => go(index - 1)}
              className='flex h-10 w-10 items-center justify-center rounded-full border border-white/10 hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'>
              <ArrowLeft className='h-4 w-4' aria-hidden='true' />
            </button>
            <button type='button' aria-label='Next feature' onClick={() => go(index + 1)}
              className='flex h-10 w-10 items-center justify-center rounded-full bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white'>
              <ArrowRight className='h-4 w-4' aria-hidden='true' />
            </button>
          </div>
        </div>

        <div key={slide.id} role='group' aria-roledescription='slide' aria-label={`${index + 1} of ${count}`} aria-live={paused ? 'polite' : 'off'}
          className='mt-9 grid items-center gap-8 rounded-[1.75rem] border border-purple-400/20 bg-[#0e0e12]/80 p-6 shadow-xl shadow-black/30 motion-safe:animate-[fadeSlide_0.5s_ease-out] sm:p-9 lg:grid-cols-[1.1fr_0.9fr]'>
          <div>
            <span className='inline-flex items-center gap-1.5 rounded-full border border-purple-400/30 bg-purple-400/10 px-3 py-1 text-xs font-semibold text-purple-200'>
              <Gauge className='h-3.5 w-3.5' aria-hidden='true' /> {slide.badge}
            </span>
            <h3 className='mt-4 text-2xl font-bold tracking-tight sm:text-3xl'>{slide.title}</h3>
            <p className='mt-3 text-sm leading-6 text-[var(--text-secondary)] sm:text-base'>{slide.description}</p>
            <ul className='mt-5 space-y-2'>
              {slide.points.map((point) => (
                <li key={point} className='flex gap-2 text-sm leading-6 text-[var(--text-secondary)]'>
                  <span className='mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-purple-300' aria-hidden='true' />{point}
                </li>
              ))}
            </ul>
          </div>
          <div>{slide.visual}</div>
        </div>

        <div className='mt-6 flex justify-center gap-2' role='tablist' aria-label='Choose a feature'>
          {slides.map((item, dot) => (
            <button key={item.id} type='button' role='tab' aria-selected={dot === index} aria-label={`Show ${item.title}`}
              onClick={() => setIndex(dot)}
              className={`h-2.5 rounded-full transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] ${dot === index ? 'w-8 bg-[var(--brand-primary)]' : 'w-2.5 bg-white/20 hover:bg-white/40'}`} />
          ))}
        </div>
      </div>
    </section>
  );
}

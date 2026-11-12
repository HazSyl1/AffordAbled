import { ArrowDown, ArrowRight, ArrowUpRight, Check, ReceiptText, Users } from 'lucide-react';
import { Link } from 'react-router-dom';

export function LandingHero({ signedIn }: { signedIn: boolean }) {
  return (
    <section className='premium-hero' aria-labelledby='landing-title'>
      <div className='premium-hero-copy'>
        <h1 id='landing-title'><span className='hero-title-first'>Your money,</span>{' '}<br /><span>beautifully understood.</span></h1>
        <p>Bring spending, accounts, and shared expenses into one calm place. See what happened, understand why, and know what to do next.</p>
        <div className='premium-hero-actions'>
          <Link className='premium-primary' to={signedIn ? '/dashboard' : '/register'}>{signedIn ? 'Open app' : 'Create your account'} <ArrowRight size={18} aria-hidden='true' /></Link>
          <a className='premium-secondary' href='#features'>Explore features <ArrowDown size={17} aria-hidden='true' /></a>
        </div>
        <p className='premium-hero-note'>Your accounts. Your decisions. A little more clarity.</p>
      </div>
      <div className='premium-product' aria-label='Demo preview of wallet activity with illustrative figures'>
        <div className='premium-dashboard'>
          <div className='premium-dashboard-top'><span>Wallet overview</span><span className='premium-demo-label'>Demo preview</span></div>
          <p className='premium-balance-label'>Across your accounts</p>
          <p className='premium-balance money'>₹48,250<span>.00</span></p>
          <div className='premium-account-line'><span>Bank account</span><span>Cash</span><span>Wallet</span></div>
          <div className='premium-chart-heading'><span>Spending this week</span><span className='money'>₹4,200</span></div>
          <div className='premium-chart' role='img' aria-label='Illustrative daily spending: Monday 500, Tuesday 800, Wednesday 400, Thursday 650, Friday 950, Saturday 600, Sunday 300 rupees.'>
            {[['M', 500], ['T', 800], ['W', 400], ['T', 650], ['F', 950], ['S', 600], ['S', 300]].map(([day, amount], index) => <div key={index}><div className='premium-bar-track'><span style={{ height: `${Number(amount) / 10}%` }} /></div><span>{day}</span></div>)}
          </div>
          <div className='premium-recent'><span className='premium-icon'><ReceiptText size={18} aria-hidden='true' /></span><div><strong>Lunch with friends</strong><span>Food & dining · Today</span></div><strong className='money'>−₹900</strong></div>
          <div className='premium-insight'><ArrowUpRight size={18} aria-hidden='true' /><p>One view of what came in,<br />what went out, and what’s shared.</p></div>
        </div>
        <div className='premium-share'><span className='premium-icon'><Users size={18} aria-hidden='true' /></span><div><strong>Dinner, split three ways.</strong><span>₹300 each · Illustrative split</span></div><Check size={16} aria-hidden='true' /></div>
      </div>
    </section>
  );
}

import '@testing-library/jest-dom/vitest';

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { ThemeProvider } from '../../features/theme/ThemeProvider';
import { LandingPage } from './LandingPage';

function renderPage() {
  return render(
    <ThemeProvider>
      <MemoryRouter><LandingPage /></MemoryRouter>
    </ThemeProvider>,
  );
}

describe('LandingPage', () => {
  afterEach(cleanup);

  it('leads with clarity, review, and shared money', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'Know where your money stands before you act.' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Four ways in. One review before anything changes.' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Shared money without the awkward arithmetic.' })).toBeInTheDocument();
  });

  it('switches the product demonstration between capture methods', () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Receipt' }));
    expect(screen.getByText('Receipt from Bombay Canteen')).toBeInTheDocument();
    expect(screen.getByText('Merchant and total extracted')).toBeInTheDocument();
  });

  it('offers working account creation and login routes', () => {
    renderPage();
    expect(screen.getAllByRole('link', { name: /Create your wallet/ })[0]).toHaveAttribute('href', '/register');
    expect(screen.getAllByRole('link', { name: 'Log in' })[0]).toHaveAttribute('href', '/login');
  });
});

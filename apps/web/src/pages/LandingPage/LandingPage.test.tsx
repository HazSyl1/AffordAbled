import '@testing-library/jest-dom/vitest';

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { store } from '../../app/store';
import { clearCredentials, setCredentials } from '../../features/auth/authSlice';
import { ThemeProvider } from '../../features/theme/ThemeProvider';
import { LandingPage } from './LandingPage';

function renderPage() {
  return render(
    <Provider store={store}>
      <ThemeProvider>
        <MemoryRouter><LandingPage /></MemoryRouter>
      </ThemeProvider>
    </Provider>,
  );
}

describe('LandingPage', () => {
  afterEach(() => {
    cleanup();
    store.dispatch(clearCredentials());
  });

  it('leads with clarity, review, and shared money', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'Track your money. Understand the story behind it.' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The everyday money tools, together.' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Good to know' })).toBeInTheDocument();
  });

  it('switches between restored feature highlights', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Next feature' }));
    expect(screen.getByRole('heading', { name: 'Remind a whole split at once' })).toBeInTheDocument();
  });

  it('offers working account creation and login routes', () => {
    renderPage();
    expect(screen.getAllByRole('link', { name: /Create your wallet/ })[0]).toHaveAttribute('href', '/register');
    expect(screen.getAllByRole('link', { name: 'Log in' })[0]).toHaveAttribute('href', '/login');
  });

  it('offers the app instead of authentication actions to signed-in users', () => {
    store.dispatch(setCredentials({ accessToken: 'test-access-token' }));
    renderPage();
    expect(screen.queryByRole('link', { name: 'Log in' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create account' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Open app/ })[0]).toHaveAttribute('href', '/dashboard');
  });
});

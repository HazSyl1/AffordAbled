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
    expect(screen.getByRole('heading', { name: 'Your money, beautifully understood.' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Everything in one place.' })).toBeInTheDocument();
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

  it('previews capture and shared expenses without saving financial records', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Voice' }));
    expect(screen.getByText('Your words become a transaction draft.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try the review step' }));
    expect(screen.getByText('Preview only. No transaction was saved.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview the split' }));
    expect(screen.getByText('Isha owes you')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset preview' }));
    expect(screen.queryByText('Isha owes you')).not.toBeInTheDocument();
  });

  it('switches the illustrative Finance Chat conversation', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Several requests' }));
    expect(screen.getByText('Create categories Food and Misc as expenses.')).toBeInTheDocument();
    expect(screen.getByText('Two requests, handled in turn.')).toBeInTheDocument();
  });

  it('offers the app instead of authentication actions to signed-in users', () => {
    store.dispatch(setCredentials({ accessToken: 'test-access-token' }));
    renderPage();
    expect(screen.queryByRole('link', { name: 'Log in' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create account' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Open app/ })[0]).toHaveAttribute('href', '/dashboard');
  });
});

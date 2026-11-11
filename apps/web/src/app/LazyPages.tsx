import { lazy } from 'react';

export const LazyAccountsPage = lazy(() => import('../pages/AccountsPage').then((module) => ({ default: module.AccountsPage })));
export const LazyChatPage = lazy(() => import('../pages/ChatPage').then((module) => ({ default: module.ChatPage })));
export const LazyDashboardPage = lazy(() => import('../pages/DashboardPage').then((module) => ({ default: module.DashboardPage })));
export const LazyLoginPage = lazy(() => import('../pages/LoginPage').then((module) => ({ default: module.LoginPage })));
export const LazyLandingPage = lazy(() => import('../pages/LandingPage/LandingPage').then((module) => ({ default: module.LandingPage })));
export const LazyProfilePage = lazy(() => import('../pages/ProfilePage').then((module) => ({ default: module.ProfilePage })));
export const LazyRegisterPage = lazy(() => import('../pages/RegisterPage').then((module) => ({ default: module.RegisterPage })));
export const LazySplitsPage = lazy(() => import('../pages/SplitsPage').then((module) => ({ default: module.SplitsPage })));
export const LazyTransactionsPage = lazy(() => import('../pages/TransactionsPage').then((module) => ({ default: module.TransactionsPage })));


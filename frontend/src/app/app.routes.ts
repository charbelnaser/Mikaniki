import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'cars' },
  {
    path: 'login',
    canActivate: [guestGuard],
    data: { mode: 'login' },
    loadComponent: () => import('./pages/auth/auth-page').then(m => m.AuthPage),
  },
  {
    path: 'register',
    canActivate: [guestGuard],
    data: { mode: 'register' },
    loadComponent: () => import('./pages/auth/auth-page').then(m => m.AuthPage),
  },
  {
    path: 'cars',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/garage/garage-page').then(m => m.GaragePage),
  },
  {
    path: 'cars/new',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/add-vehicle/add-vehicle-page').then(m => m.AddVehiclePage),
  },
  {
    path: 'cars/:vehicleId/parts',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/parts/parts-page').then(m => m.PartsPage),
  },
  // One route for new + existing conversations, so the chat component is reused
  // (no reload/flicker) when a new conversation gets its id.
  { path: 'cars/:vehicleId/chat', pathMatch: 'full', redirectTo: 'cars/:vehicleId/chat/new' },
  {
    path: 'cars/:vehicleId/chat/:conversationId',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/chat/chat-page').then(m => m.ChatPage),
  },
  { path: '**', redirectTo: 'cars' },
];

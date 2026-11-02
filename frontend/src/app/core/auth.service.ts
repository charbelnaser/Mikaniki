import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, map, of, switchMap, tap } from 'rxjs';

import { ApiService } from './api.service';
import { I18nService } from './i18n.service';
import { Lang, User } from './models';

const TOKEN_KEY = 'mk_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private api = inject(ApiService);
  private router = inject(Router);
  private i18n = inject(I18nService);

  readonly token = signal<string | null>(localStorage.getItem(TOKEN_KEY));
  readonly user = signal<User | null>(null);
  readonly isLoggedIn = computed(() => !!this.token());

  login(email: string, password: string): Observable<User> {
    return this.api.login({ email, password }).pipe(switchMap(r => this.startSession(r.access_token)));
  }

  register(email: string, password: string, fullName: string): Observable<User> {
    return this.api
      .register({ email, password, full_name: fullName || undefined, language: this.i18n.lang() })
      .pipe(switchMap(r => this.startSession(r.access_token)));
  }

  /** Load the current user once at startup (if a token exists). */
  restore(): Observable<User | null> {
    if (!this.token()) return of(null);
    return this.api.me().pipe(
      tap(u => this.user.set(u)),
      catchError(() => {
        this.clear();
        return of(null);
      }),
    );
  }

  setLanguage(lang: Lang) {
    this.i18n.setLang(lang);
    if (this.token()) this.api.setLanguage(lang).subscribe(u => this.user.set(u));
  }

  logout() {
    this.clear();
    this.router.navigateByUrl('/login');
  }

  clear() {
    localStorage.removeItem(TOKEN_KEY);
    this.token.set(null);
    this.user.set(null);
  }

  private startSession(token: string): Observable<User> {
    localStorage.setItem(TOKEN_KEY, token);
    this.token.set(token);
    return this.api.me().pipe(
      tap(u => this.user.set(u)),
      map(u => u),
    );
  }
}

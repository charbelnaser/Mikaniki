import { Component, computed, inject, input, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';
import { TranslatePipe } from '../../shared/translate.pipe';

@Component({
  selector: 'app-auth-page',
  imports: [ReactiveFormsModule, RouterLink, TranslatePipe],
  template: `
    <section class="page page-narrow">
      <div class="hero">
        <h1>{{ (isRegister() ? 'auth.registerTitle' : 'auth.loginTitle') | t }}</h1>
        <p class="muted">{{ (isRegister() ? 'auth.registerSub' : 'app.tagline') | t }}</p>
      </div>

      <form class="card" [formGroup]="form" (ngSubmit)="submit()">
        @if (error()) {
          <div class="alert alert-error" role="alert">{{ error() }}</div>
        }

        @if (isRegister()) {
          <div class="field">
            <label for="name">{{ 'auth.name' | t }}</label>
            <input id="name" formControlName="fullName" autocomplete="name" />
          </div>
        }

        <div class="field">
          <label for="email">{{ 'auth.email' | t }}</label>
          <input id="email" type="email" dir="ltr" formControlName="email" autocomplete="email" />
        </div>

        <div class="field">
          <label for="password">{{ 'auth.password' | t }}</label>
          <input id="password" type="password" dir="ltr" formControlName="password"
                 [attr.autocomplete]="isRegister() ? 'new-password' : 'current-password'" />
          @if (isRegister()) { <small>{{ 'auth.passwordHint' | t }}</small> }
        </div>

        <button class="btn btn-primary btn-block" type="submit" [disabled]="form.invalid || busy()">
          {{ (isRegister() ? 'auth.register' : 'auth.login') | t }}
        </button>

        <p class="switch muted">
          @if (isRegister()) {
            {{ 'auth.haveAccount' | t }} <a routerLink="/login">{{ 'auth.login' | t }}</a>
          } @else {
            {{ 'auth.noAccount' | t }} <a routerLink="/register">{{ 'auth.register' | t }}</a>
          }
        </p>
      </form>
    </section>
  `,
  styles: `
    .hero { margin: 24px 0 20px; }
    .switch { text-align: center; margin: 16px 0 0; font-size: .92rem; }
  `,
})
export class AuthPage {
  /** Bound from the route's `data.mode` (withComponentInputBinding). */
  readonly mode = input<'login' | 'register'>('login');
  protected readonly isRegister = computed(() => this.mode() === 'register');

  private fb = inject(FormBuilder);
  private auth = inject(AuthService);
  private api = inject(ApiService);
  private router = inject(Router);
  private i18n = inject(I18nService);

  protected busy = signal(false);
  protected error = signal<string | null>(null);

  protected form = this.fb.nonNullable.group({
    fullName: [''],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8)]],
  });

  submit() {
    if (this.form.invalid) return;
    const { email, password, fullName } = this.form.getRawValue();
    this.busy.set(true);
    this.error.set(null);

    const session$ = this.isRegister()
      ? this.auth.register(email, password, fullName)
      : this.auth.login(email, password);

    // Like Carmy: the very first thing a new user does is identify their car.
    session$.pipe(switchMap(() => this.api.vehicles())).subscribe({
      next: cars => this.router.navigateByUrl(cars.length ? '/cars' : '/cars/new'),
      error: err => {
        this.busy.set(false);
        if (err?.status === 401) this.error.set(this.i18n.t('auth.badCredentials'));
        else if (typeof err?.error?.detail === 'string') this.error.set(err.error.detail);
        else this.error.set(this.i18n.t('errors.generic'));
      },
    });
  }
}

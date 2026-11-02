import { Component, inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

import { AuthService } from './core/auth.service';
import { I18nService } from './core/i18n.service';
import { Lang } from './core/models';
import { TranslatePipe } from './shared/translate.pipe';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, TranslatePipe],
  template: `
    <header class="topbar">
      <a class="brand" routerLink="/cars">
        <img src="icon.svg" alt="" width="32" height="32" />
        <span>{{ 'app.name' | t }}</span>
      </a>

      <nav class="topbar-actions">
        <div class="lang-switch" role="group" aria-label="Language">
          @for (l of langs; track l.code) {
            <button type="button" [class.active]="i18n.lang() === l.code" (click)="setLang(l.code)">
              {{ l.label }}
            </button>
          }
        </div>
        @if (auth.isLoggedIn()) {
          <a class="link" routerLink="/cars">{{ 'nav.myCars' | t }}</a>
          <button type="button" class="link" (click)="auth.logout()">{{ 'nav.logout' | t }}</button>
        }
      </nav>
    </header>

    <main>
      <router-outlet />
    </main>
  `,
  styles: `
    :host { display: flex; flex-direction: column; min-height: 100dvh; }
    .topbar {
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 12px 20px; background: var(--ink); color: var(--paper);
      position: sticky; top: 0; z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 10px; color: inherit; text-decoration: none;
      font-weight: 700; font-size: 1.15rem; }
    .topbar-actions { display: flex; align-items: center; gap: 16px; }
    .lang-switch { display: flex; border: 1px solid rgba(255,255,255,.25); border-radius: 999px; overflow: hidden; }
    .lang-switch button { background: none; border: 0; color: var(--paper); padding: 4px 10px;
      font: inherit; font-size: .85rem; cursor: pointer; opacity: .7; }
    .lang-switch button.active { background: var(--accent); color: var(--ink); opacity: 1; font-weight: 600; }
    .link { background: none; border: 0; color: var(--paper); font: inherit; cursor: pointer;
      text-decoration: none; opacity: .85; }
    .link:hover { opacity: 1; }
    main { flex: 1; display: flex; flex-direction: column; }
    @media (max-width: 560px) { .topbar a.link { display: none; } .brand span { display: none; } }
  `,
})
export class App {
  protected auth = inject(AuthService);
  protected i18n = inject(I18nService);

  protected langs: { code: Lang; label: string }[] = [
    { code: 'ar', label: 'عربي' },
    { code: 'en', label: 'EN' },
    { code: 'fr', label: 'FR' },
  ];

  setLang(lang: Lang) {
    this.auth.setLanguage(lang);
  }
}

import { Injectable, computed, effect, signal } from '@angular/core';

import { Lang } from './models';
import { TRANSLATIONS } from './translations';

const LANG_KEY = 'mk_lang';

function initialLang(): Lang {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved === 'ar' || saved === 'en' || saved === 'fr') return saved;
  const nav = navigator.language.slice(0, 2);
  return nav === 'en' || nav === 'fr' ? nav : 'ar';
}

/** Tiny runtime i18n: switch language without reloading, RTL for Arabic. */
@Injectable({ providedIn: 'root' })
export class I18nService {
  readonly lang = signal<Lang>(initialLang());
  readonly dir = computed(() => (this.lang() === 'ar' ? 'rtl' : 'ltr'));

  constructor() {
    effect(() => {
      const lang = this.lang();
      document.documentElement.lang = lang;
      document.documentElement.dir = this.dir();
      localStorage.setItem(LANG_KEY, lang);
    });
  }

  setLang(lang: Lang) {
    this.lang.set(lang);
  }

  t(key: string, params?: Record<string, string | number>): string {
    const dict = TRANSLATIONS[this.lang()];
    let text = dict[key] ?? TRANSLATIONS.en[key] ?? key;
    if (params) {
      for (const [k, v] of Object.entries(params)) text = text.replaceAll(`{${k}}`, String(v));
    }
    return text;
  }
}

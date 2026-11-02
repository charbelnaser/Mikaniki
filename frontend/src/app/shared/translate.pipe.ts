import { Pipe, PipeTransform, inject } from '@angular/core';

import { I18nService } from '../core/i18n.service';

/** Usage: {{ 'garage.title' | t }}  or  {{ 'chat.welcome' | t: { car: name } }} */
@Pipe({ name: 't', pure: false })
export class TranslatePipe implements PipeTransform {
  private i18n = inject(I18nService);

  transform(key: string, params?: Record<string, string | number>): string {
    return this.i18n.t(key, params);
  }
}

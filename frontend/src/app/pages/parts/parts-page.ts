import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { PartCategory, PartList, Vehicle } from '../../core/models';
import { TranslatePipe } from '../../shared/translate.pipe';

/**
 * Original parts catalog (EPC) of the car, by VIN: sections -> sub-sections -> exploded diagram
 * with the OE part numbers. Data from 17VIN through the backend (routers/parts.py).
 */
@Component({
  selector: 'app-parts-page',
  imports: [RouterLink, TranslatePipe],
  template: `
    <section class="page">
      <div class="row head">
        <div>
          <h1>{{ 'parts.title' | t }}</h1>
          @if (vehicle(); as v) {
            <p class="muted car">{{ v.year }} {{ v.make }} {{ v.model }} · <span dir="ltr">{{ v.vin }}</span></p>
          }
        </div>
        <span class="spacer"></span>
        <a class="btn btn-ghost" [routerLink]="['/cars', vehicleId(), 'chat']">{{ 'parts.back' | t }}</a>
      </div>

      <nav class="trail">
        <button type="button" class="crumb" [class.current]="!trail().length" (click)="goTo(0)">{{ 'parts.all' | t }}</button>
        @for (c of trail(); track c.code; let i = $index) {
          <span aria-hidden="true">›</span>
          <button type="button" class="crumb" [class.current]="i === trail().length - 1" (click)="goTo(i + 1)" dir="auto">
            {{ c.name }}
          </button>
        }
      </nav>

      @if (error(); as e) {
        <div class="card error">{{ e | t }}</div>
        @if (vehicle()?.vin; as vin) {
          <!-- Fallback while 17VIN is not available: the same VIN on PartSouq (also linked in the chat) -->
          <a class="btn btn-accent fallback" [href]="'https://partsouq.com/en/search/all?q=' + vin"
             target="_blank" rel="noopener">🛒 {{ 'media.partsouq' | t }}</a>
        }
      } @else if (loading()) {
        <p class="muted">{{ 'common.loading' | t }}</p>
      } @else if (list(); as l) {
        <div class="tools">
          <input type="search" [placeholder]="'parts.filter' | t" [value]="filter()"
                 (input)="filter.set($any($event.target).value)" />
          <label class="muted small"><input type="checkbox" [checked]="showAll()" (change)="showAll.set(!showAll())" />
            {{ 'parts.showAll' | t }}</label>
        </div>
        <div class="parts-layout">
          @if (l.image) {
            <div class="diagram card">
              <div class="canvas">
                <img [src]="l.image" [alt]="trail().at(-1)?.name ?? ''" />
                @for (h of l.hotspots; track $index) {
                  <button type="button" class="spot" [class.on]="h.callout === selected()"
                          [style.left.%]="h.x" [style.top.%]="h.y" [title]="h.callout"
                          [attr.aria-label]="h.callout" (click)="select(h.callout, true)"></button>
                }
              </div>
              <a class="small muted zoom" [href]="l.image" target="_blank" rel="noopener">🔍 {{ 'parts.zoom' | t }}</a>
            </div>
          }
          <div class="card table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{{ 'parts.callout' | t }}</th>
                  <th>{{ 'parts.number' | t }}</th>
                  <th>{{ 'parts.name' | t }}</th>
                  <th>{{ 'parts.qty' | t }}</th>
                </tr>
              </thead>
              <tbody>
                @for (p of visibleParts(); track $index) {
                  <tr [class.dim]="!p.fits" [class.on]="!!p.callout && p.callout === selected()"
                      [attr.data-callout]="p.callout" (click)="select(p.callout)">
                    <td class="callout" dir="ltr">{{ p.callout }}</td>
                    <td class="number" dir="ltr">
                      <code>{{ p.number }}</code>
                      <button type="button" class="copy" (click)="copy(p.number); $event.stopPropagation()">
                        {{ (copied() === p.number ? 'parts.copied' : 'parts.copy') | t }}
                      </button>
                    </td>
                    <td dir="auto">
                      {{ p.name }}
                      @if (p.remark) { <small class="muted block">{{ p.remark }}</small> }
                      @if (p.replacement) { <small class="block warn">{{ 'parts.replacedBy' | t: { n: p.replacement } }}</small> }
                      @if (!p.fits) { <small class="muted block">{{ 'parts.notForVin' | t }}</small> }
                    </td>
                    <td dir="ltr">{{ p.qty }}</td>
                  </tr>
                } @empty {
                  <tr><td colspan="4" class="muted">{{ 'parts.empty' | t }}</td></tr>
                }
              </tbody>
            </table>
          </div>
        </div>
        <p class="muted small">💡 {{ 'parts.tip' | t }}</p>
      } @else {
        @if (!trail().length) { <p class="muted">{{ 'parts.intro' | t }}</p> }
        <label class="muted small toggle"><input type="checkbox" [checked]="showAll()" (change)="showAll.set(!showAll())" />
          {{ 'parts.showAll' | t }}</label>
        <div class="grid">
          @for (c of visibleCategories(); track c.code) {
            <button type="button" class="card section" [class.dim]="!c.fits" (click)="open(c)">
              @if (c.image) { <img [src]="c.image" alt="" loading="lazy" referrerpolicy="no-referrer" /> }
              <strong dir="auto">{{ c.name }}</strong>
              @if (c.remark) { <small class="muted" dir="auto">{{ c.remark }}</small> }
              @if (!c.fits) { <small class="muted">{{ 'parts.notForVin' | t }}</small> }
            </button>
          } @empty {
            <p class="muted">{{ 'parts.empty' | t }}</p>
          }
        </div>
      }
    </section>
  `,
  styles: `
    .head { margin-bottom: 8px; align-items: flex-start; }
    .car { margin: 4px 0 0; }
    .trail { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 8px 0 16px; color: var(--muted); }
    .crumb { background: none; border: 0; padding: 2px 0; font: inherit; color: var(--ink-2); cursor: pointer;
      text-decoration: underline; }
    .crumb.current { text-decoration: none; font-weight: 700; color: var(--ink); cursor: default; }
    .error { color: var(--danger); }
    .fallback { margin-top: 12px; }
    .toggle { display: block; margin-bottom: 12px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
    .section { display: flex; flex-direction: column; gap: 6px; text-align: start; cursor: pointer; font: inherit;
      color: var(--ink); }
    .section:hover { border-color: var(--ink-2); }
    .section img { width: 100%; height: 110px; object-fit: contain; background: #fff; border-radius: 8px; }
    .dim { opacity: .55; }
    .tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-bottom: 12px; }
    .tools input[type=search] { max-width: 320px; }
    .parts-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); gap: 16px;
      align-items: start; margin-bottom: 12px; }
    @media (max-width: 800px) { .parts-layout { grid-template-columns: 1fr; } }
    .diagram { padding: 8px; background: #fff; position: sticky; top: 72px; }
    .canvas { position: relative; }
    .canvas img { width: 100%; display: block; }
    /* Hotspot = top-left corner of the callout label on the drawing */
    .spot { position: absolute; width: 7.5%; min-width: 26px; aspect-ratio: 2.6 / 1; padding: 0; cursor: pointer;
      border: 2px solid transparent; border-radius: 4px; background: rgba(242, 163, 58, .18);
      transition: background .15s ease, border-color .15s ease; }
    .spot:hover { background: rgba(242, 163, 58, .4); }
    .spot.on { background: rgba(242, 163, 58, .55); border-color: var(--accent-ink); }
    .zoom { display: inline-block; margin-top: 6px; }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: #faf8f4; }
    tbody tr.on { background: #fff4e5; }
    tbody tr.on .callout { color: var(--accent-ink); font-weight: 700; }
    .table-wrap { padding: 0; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: .9rem; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: start; vertical-align: top; }
    th { font-size: .75rem; text-transform: uppercase; color: var(--muted); }
    .callout { color: var(--muted); }
    .number { white-space: nowrap; }
    .number code { font-weight: 700; }
    .copy { margin-inline-start: 6px; font-size: .72rem; padding: 2px 8px; border-radius: 999px;
      border: 1px solid var(--line); background: var(--card); cursor: pointer; }
    .block { display: block; }
    .warn { color: var(--accent-ink); }
    .small { font-size: .85rem; }
  `,
})
export class PartsPage implements OnInit {
  private api = inject(ApiService);

  /** Route param (withComponentInputBinding). */
  vehicleId = input.required<string>();
  /** Optional query params (links under chat answers): open this last-level section directly. */
  section = input<string>();
  level = input<string>();
  name = input<string>();

  protected vehicle = signal<Vehicle | null>(null);
  /** Sections opened so far; the last one is shown. */
  protected trail = signal<PartCategory[]>([]);
  protected categories = signal<PartCategory[]>([]);
  protected list = signal<PartList | null>(null);
  protected loading = signal(true);
  /** Translation key */
  protected error = signal<string | null>(null);
  protected showAll = signal(false);
  protected filter = signal('');
  protected copied = signal<string | null>(null);
  /** Callout highlighted on the diagram and in the table. */
  protected selected = signal<string | null>(null);

  protected visibleCategories = computed(() =>
    this.showAll() ? this.categories() : this.categories().filter(c => c.fits));

  protected visibleParts = computed(() => {
    const q = this.filter().trim().toLowerCase();
    return (this.list()?.parts ?? [])
      .filter(p => this.showAll() || p.fits)
      .filter(p => !q || [p.number, p.name, p.name_zh, p.callout].some(v => v?.toLowerCase().includes(q)));
  });

  private get id(): number {
    return Number(this.vehicleId());
  }

  ngOnInit() {
    this.api.vehicle(this.id).subscribe({ next: v => this.vehicle.set(v), error: () => {} });
    const code = this.section();
    if (code && Number(this.level())) {
      this.trail.set([{ code, name: this.name() || code, level: Number(this.level()), is_last: true, fits: true,
                        name_zh: null, remark: null, image: null }]);
    }
    this.load();
  }

  protected open(c: PartCategory) {
    this.trail.update(t => [...t, c]);
    this.load();
  }

  /** Back to the first `depth` sections of the trail (0 = all sections). */
  protected goTo(depth: number) {
    if (depth === this.trail().length && !this.error()) return;
    this.trail.update(t => t.slice(0, depth));
    this.load();
  }

  /** Link the diagram and the table; from the diagram, scroll the part's row into view. */
  protected select(callout: string | null, scroll = false) {
    if (!callout) return;
    this.selected.set(this.selected() === callout && !scroll ? null : callout);
    if (scroll) {
      document.querySelector(`tr[data-callout="${CSS.escape(callout)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  protected copy(number: string) {
    navigator.clipboard?.writeText(number).then(() => this.copied.set(number), () => {});
  }

  private load() {
    const last = this.trail().at(-1);
    this.loading.set(true);
    this.error.set(null);
    this.filter.set('');
    this.selected.set(null);
    this.list.set(null);
    const done = { error: (e: HttpErrorResponse) => this.fail(e) };
    if (last?.is_last) {
      this.api.partList(this.id, last).subscribe({ ...done, next: l => this.show(l, []) });
    } else {
      this.api.partCategories(this.id, last).subscribe({ ...done, next: cs => this.show(null, cs) });
    }
  }

  private show(list: PartList | null, categories: PartCategory[]) {
    this.list.set(list);
    this.categories.set(categories);
    this.loading.set(false);
  }

  private fail(e: HttpErrorResponse) {
    this.loading.set(false);
    this.error.set(e.status === 409 ? 'parts.noVin' : e.status === 404 ? 'parts.notFound' : 'parts.unavailable');
  }
}

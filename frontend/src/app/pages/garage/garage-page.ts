import { DecimalPipe } from '@angular/common';
import { Component, HostListener, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { I18nService } from '../../core/i18n.service';
import { Vehicle, VehicleReports } from '../../core/models';
import { TranslatePipe } from '../../shared/translate.pipe';

@Component({
  selector: 'app-garage-page',
  imports: [RouterLink, TranslatePipe, DecimalPipe],
  template: `
    <section class="page">
      <div class="row head">
        <div>
          <h1>{{ 'garage.title' | t }}</h1>
          @if (vehicles().length) { <p class="muted subtitle">{{ 'garage.subtitle' | t }}</p> }
        </div>
        <span class="spacer"></span>
        @if (vehicles().length) {
          <a class="btn btn-primary" routerLink="/cars/new">+ {{ 'garage.addCar' | t }}</a>
        }
      </div>

      @if (loading()) {
        <p class="muted">{{ 'common.loading' | t }}</p>
      } @else if (!vehicles().length) {
        <div class="card empty">
          <div class="empty-icon" aria-hidden="true">🚗</div>
          <h2>{{ 'garage.emptyTitle' | t }}</h2>
          <p class="muted">{{ 'garage.emptyText' | t }}</p>
          <a class="btn btn-accent" routerLink="/cars/new">+ {{ 'garage.addCar' | t }}</a>
        </div>
      } @else {
        <div class="grid">
          @for (v of vehicles(); track v.id) {
            <article class="card car">
              <div class="car-top">
                <span class="avatar" aria-hidden="true">{{ v.make.charAt(0) }}</span>
                <div class="car-title">
                  <span class="make">{{ v.make }}@if (v.nickname) { <span class="muted nick"> · {{ v.nickname }}</span> }</span>
                  <h2>{{ v.year }} {{ v.model }}</h2>
                </div>
                <button class="icon-remove" type="button" (click)="remove(v)"
                        [title]="'garage.delete' | t" [attr.aria-label]="'garage.delete' | t">✕</button>
              </div>
              <ul class="specs muted">
                @if (v.trim) { <li>{{ v.trim }}</li> }
                @if (v.engine) { <li>{{ v.engine }}</li> }
                @if (v.fuel_type) { <li>{{ v.fuel_type }}</li> }
                @if (v.mileage_km != null) { <li dir="ltr">{{ v.mileage_km | number }} km</li> }
              </ul>
              @if (v.vin) { <p class="vin"><span dir="ltr">VIN {{ v.vin }}</span></p> }
              @if (reports()[v.id]; as r) {
                @if (r.available) {
                  <button class="safety" type="button" [title]="'garage.details' | t" (click)="openDetails(v)">
                    @if (recallCount(r); as n) {
                      <span class="pill pill-warn" [title]="recallTitle(r)">⚠ {{ 'garage.recalls' | t: { n } }}</span>
                    } @else {
                      <span class="pill pill-ok">✓ {{ 'garage.noRecalls' | t }}</span>
                    }
                    @if (stars(r); as n) {
                      <span class="pill" [title]="r.safety?.description ?? ''">★ {{ 'garage.safety' | t: { n } }}</span>
                    }
                    @if (r.complaints) {
                      <span class="pill pill-muted">{{ 'garage.complaints' | t: { n: r.complaints } }}</span>
                    }
                    <span class="more" aria-hidden="true">›</span>
                  </button>
                }
              }
              <div class="actions">
                <a class="btn btn-primary" [routerLink]="['/cars', v.id, 'chat']">🔧 {{ 'garage.diagnose' | t }}</a>
                @if (v.vin) {
                  <a class="btn btn-ghost" [routerLink]="['/cars', v.id, 'parts']">🔩 {{ 'parts.short' | t }}</a>
                }
              </div>
            </article>
          }
        </div>
      }

      @if (details(); as d) {
        <div class="backdrop" (click)="details.set(null)">
          <div class="card sheet" role="dialog" aria-modal="true" [attr.aria-label]="'garage.details' | t"
               (click)="$event.stopPropagation()">
            <div class="row sheet-head">
              <h2>{{ d.car.year }} {{ d.car.make }} {{ d.car.model }}</h2>
              <span class="spacer"></span>
              <button class="btn" type="button" (click)="details.set(null)">{{ 'garage.close' | t }}</button>
            </div>

            @if (stars(d.r); as n) {
              <p class="muted">★ {{ 'garage.safety' | t: { n } }} — {{ d.r.safety?.description }}</p>
            }

            <h3>{{ 'garage.recallsTitle' | t }} ({{ d.r.recalls.length }})</h3>
            @for (rc of d.r.recalls; track rc.market + rc.ref) {
              <div class="item" [class.danger]="rc.park_it">
                <div class="item-head">
                  <span class="pill">{{ 'garage.market.' + rc.market | t }}</span>
                  <b dir="ltr">{{ rc.ref }}</b>
                  @if (rc.date) { <span class="muted" dir="ltr">{{ rc.date }}</span> }
                </div>
                @if (rc.park_it) { <p class="park">⛔ {{ 'garage.parkIt' | t }}</p> }
                @if (rc.component) { <p class="comp" dir="ltr">{{ rc.component }}</p> }
                <div dir="ltr" class="en">
                  @if (rc.summary) { <p>{{ rc.summary }}</p> }
                  @if (rc.consequence) { <p><b>{{ 'garage.risk' | t }}:</b> {{ rc.consequence }}</p> }
                  @if (rc.remedy) { <p><b>{{ 'garage.fix' | t }}:</b> {{ rc.remedy }}</p> }
                </div>
              </div>
            } @empty {
              <p class="muted">✓ {{ 'garage.noRecalls' | t }}</p>
            }

            @if (d.r.complaints) {
              <h3>{{ 'garage.complaintsTitle' | t }} ({{ d.r.complaints }})</h3>
              <p class="muted">{{ 'garage.incidents' | t: { crashes: d.r.crashes, fires: d.r.fires, injuries: d.r.injuries } }}</p>
              @for (c of d.r.top_components; track c.component) {
                <div class="item">
                  <div class="item-head">
                    <b dir="ltr">{{ c.component }}</b>
                    <span class="spacer"></span>
                    <span class="pill pill-muted">{{ 'garage.componentCount' | t: { n: c.count } }}</span>
                  </div>
                  @for (ex of c.examples; track $index) {
                    <blockquote dir="ltr" class="en">“{{ ex }}”</blockquote>
                  }
                </div>
              }
            }

            <p class="muted note">{{ 'garage.officialNote' | t }}</p>
          </div>
        </div>
      }
    </section>
  `,
  styles: `
    .head { margin-bottom: 16px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
    .subtitle { margin: 0; }
    .car h2 { font-size: 1.2rem; margin: 0; }
    .car { transition: transform .15s ease, box-shadow .15s ease; }
    .car:hover { transform: translateY(-2px); box-shadow: 0 2px 4px rgba(15, 27, 45, .06), 0 12px 28px rgba(15, 27, 45, .1); }
    .car-top { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
    .avatar { flex: none; width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
      background: var(--ink); color: var(--accent); font-weight: 700; font-size: 1.3rem; }
    .car-title { display: flex; flex-direction: column; min-width: 0; flex: 1; }
    .make { font-size: .8rem; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--accent-ink); }
    .make .nick { text-transform: none; letter-spacing: 0; font-weight: 500; }
    .icon-remove { flex: none; align-self: flex-start; width: 30px; height: 30px; border-radius: 50%; border: 0;
      background: none; color: var(--muted); cursor: pointer; font-size: .9rem; }
    .icon-remove:hover { background: #fff1ec; color: var(--danger); }
    .vin { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; letter-spacing: .04em;
      color: var(--muted); margin: -6px 0 12px; }
    .badge { background: var(--accent); color: var(--ink); font-weight: 700; font-size: .8rem;
      padding: 2px 10px; border-radius: 999px; }
    .nick { font-size: .85rem; }
    .specs { list-style: none; padding: 0; margin: 0 0 14px; display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: .9rem; }
    .actions { margin-top: auto; display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
    .car { display: flex; flex-direction: column; }
    .empty { text-align: center; padding: 40px 24px; }
    .empty-icon { font-size: 2.5rem; }
    .safety { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: -6px 0 14px; padding: 0;
      background: none; border: 0; cursor: pointer; text-align: start; font: inherit; }
    .safety:hover .pill { filter: brightness(.97); }
    .more { color: var(--muted); font-weight: 700; }
    :host-context([dir=rtl]) .more { transform: scaleX(-1); }
    .backdrop { position: fixed; inset: 0; z-index: 50; background: rgba(15, 27, 45, .45);
      display: flex; align-items: center; justify-content: center; padding: 16px; }
    .sheet { width: min(640px, 100%); max-height: 90vh; overflow-y: auto; }
    .sheet h2 { font-size: 1.15rem; margin: 0; }
    .sheet h3 { font-size: 1rem; margin: 18px 0 8px; }
    .sheet-head { align-items: center; margin-bottom: 8px; }
    .item { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; }
    .item.danger { border-color: var(--danger); }
    .item-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
    .item p { margin: 6px 0 0; font-size: .9rem; }
    .comp { font-weight: 600; color: var(--ink-2); }
    .park { color: var(--danger); font-weight: 700; }
    .en { text-align: left; }
    blockquote { margin: 6px 0 0; padding-left: 10px; border-left: 3px solid var(--line); font-size: .85rem; color: var(--ink-2); }
    .note { font-size: .82rem; margin-top: 14px; }
    .pill { font-size: .78rem; font-weight: 600; padding: 2px 9px; border-radius: 999px;
      background: #eef2f7; color: var(--ink); border: 1px solid var(--line); }
    .pill-warn { background: #fff4e5; border-color: #f5c98b; color: #8a4b00; }
    .pill-ok { background: #effaf2; border-color: #c8ecd3; color: var(--ok); }
    .pill-muted { color: var(--muted); }
  `,
})
export class GaragePage {
  private api = inject(ApiService);
  private i18n = inject(I18nService);

  protected vehicles = signal<Vehicle[]>([]);
  protected loading = signal(true);
  /** Safety summary per car id; loaded after the list (also warms the backend cache for the chat). */
  protected reports = signal<Record<number, VehicleReports>>({});
  /** Car whose recalls / complaints are shown in the details dialog. */
  protected details = signal<{ car: Vehicle; r: VehicleReports } | null>(null);

  constructor() {
    this.api.vehicles().subscribe({
      next: v => {
        this.vehicles.set(v);
        this.loading.set(false);
        for (const car of v) {
          this.api.vehicleReports(car.id).subscribe({
            next: r => this.reports.update(all => ({ ...all, [car.id]: r })),
          });
        }
      },
      error: () => this.loading.set(false),
    });
  }

  openDetails(car: Vehicle) {
    const r = this.reports()[car.id];
    if (r) this.details.set({ car, r });
  }

  @HostListener('document:keydown.escape')
  closeDetails() {
    this.details.set(null);
  }

  recallCount(r: VehicleReports): number {
    return r.recalls_us + r.recalls_canada + r.recalls_uk;
  }

  /** Overall crash-test stars, or null when the car was not rated. */
  stars(r: VehicleReports): string | null {
    const overall = r.safety?.overall;
    return overall && overall !== 'Not Rated' ? overall : null;
  }

  recallTitle(r: VehicleReports): string {
    return [['US', r.recalls_us], ['Canada', r.recalls_canada], ['UK', r.recalls_uk]]
      .filter(([, n]) => n)
      .map(([label, n]) => `${label}: ${n}`)
      .join(' · ');
  }

  remove(v: Vehicle) {
    if (!confirm(this.i18n.t('garage.confirmDelete', { car: v.display_name }))) return;
    this.api.deleteVehicle(v.id).subscribe(() => this.vehicles.update(list => list.filter(x => x.id !== v.id)));
  }
}

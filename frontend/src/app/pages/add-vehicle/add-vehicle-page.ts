import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import {
  catchError, combineLatest, debounceTime, distinctUntilChanged, filter, of, startWith, switchMap, tap,
} from 'rxjs';

import { ApiService, apiError } from '../../core/api.service';
import { I18nService } from '../../core/i18n.service';
import { CarModel, EpaVersion, Make, VehicleSource, VinDecode } from '../../core/models';
import { TranslatePipe } from '../../shared/translate.pipe';

const FUELS = ['gasoline', 'diesel', 'hybrid', 'electric', 'lpg'] as const;
const GEARBOXES = ['automatic', 'manual', 'cvt', 'dct'] as const;

/** Map free-text values from the VIN decoder to our select options. */
function normalizeFuel(v: string | null): string {
  const s = (v ?? '').toLowerCase();
  if (s.includes('hybrid')) return 'hybrid';
  if (s.includes('electric')) return 'electric';
  if (s.includes('diesel')) return 'diesel';
  if (s.includes('gasoline') || s.includes('petrol') || s.includes('flex')) return 'gasoline';
  if (s.includes('lpg') || s.includes('propane')) return 'lpg';
  return '';
}
function normalizeGearbox(v: string | null): string {
  const s = (v ?? '').toLowerCase();
  // EPA spellings: "Auto (AV-S7)" / "variable gear ratios" = CVT, "Auto (AM-S7)" = dual-clutch
  if (s.includes('cvt') || s.includes('continuously') || s.includes('av-s') || s.includes('variable gear')) return 'cvt';
  if (s.includes('dual') || s.includes('dct') || s.includes('am-s') || s.includes('(am')) return 'dct';
  if (s.includes('manual') || s.includes('standard')) return 'manual';
  if (s.includes('auto')) return 'automatic';
  return '';
}
/** "Auto (S6), 4 cyl, 2.0 L, Turbo" -> "2.0L 4 cyl turbo" */
function engineFromVersion(text: string): string {
  const displ = text.match(/(\d+(?:\.\d+)?)\s*L\b/)?.[1];
  const cyl = text.match(/(\d+)\s*cyl/)?.[1];
  const turbo = /turbo/i.test(text) ? ' turbo' : '';
  return [displ && `${displ}L`, cyl && `${cyl} cyl`].filter(Boolean).join(' ') + turbo;
}

/**
 * Phone photos are often 3-10 MB: re-encode as a JPEG of at most 2000 px, still sharp enough
 * to read a VIN. Falls back to the original file if the browser cannot decode it (e.g. HEIC).
 */
async function shrinkImage(file: File, maxSide = 2000): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9));
    return blob ?? file;
  } catch {
    return file;
  }
}

@Component({
  selector: 'app-add-vehicle-page',
  imports: [ReactiveFormsModule, RouterLink, TranslatePipe],
  templateUrl: './add-vehicle-page.html',
  styleUrl: './add-vehicle-page.css',
})
export class AddVehiclePage {
  private api = inject(ApiService);
  private router = inject(Router);
  private fb = inject(FormBuilder);
  private i18n = inject(I18nService);
  private destroyRef = inject(DestroyRef);

  protected readonly fuels = FUELS;
  protected readonly gearboxes = GEARBOXES;
  protected readonly years: number[] = Array.from(
    { length: new Date().getFullYear() + 2 - 1980 },
    (_, i) => new Date().getFullYear() + 1 - i,
  );

  protected tab = signal<VehicleSource>('catalog');
  protected makes = signal<Make[]>([]);
  protected popularMakes = computed(() => this.makes().filter(m => m.popular));
  protected models = signal<CarModel[]>([]);
  protected modelsLoading = signal(false);

  protected versions = signal<EpaVersion[]>([]);
  protected versionsLoading = signal(false);

  protected vinCtrl = new FormControl('', { nonNullable: true, validators: [Validators.pattern(/^[A-HJ-NPR-Za-hj-npr-z0-9]{17}$/)] });
  protected vinResult = signal<VinDecode | null>(null);
  protected vinBusy = signal(false);
  protected vinReading = signal(false);

  protected saving = signal(false);
  protected error = signal<string | null>(null);

  protected form = this.fb.group({
    year: this.fb.control<number | null>(null, Validators.required),
    make: this.fb.nonNullable.control('', Validators.required),
    model: this.fb.nonNullable.control('', Validators.required),
    trim: this.fb.nonNullable.control(''),
    engine: this.fb.nonNullable.control(''),
    fuel_type: this.fb.nonNullable.control(''),
    transmission: this.fb.nonNullable.control(''),
    mileage_km: this.fb.control<number | null>(null, [Validators.min(0), Validators.max(2_000_000)]),
    nickname: this.fb.nonNullable.control(''),
    epa_id: this.fb.control<number | null>(null),
  });

  /** In the VIN tab, details only appear once the car was found. */
  protected showDetails = computed(() => this.tab() !== 'vin' || !!this.vinResult());

  constructor() {
    this.api.makes().pipe(takeUntilDestroyed()).subscribe({ next: m => this.makes.set(m) });

    // Catalog: reload the model list whenever year + make change
    const make$ = this.form.controls.make.valueChanges.pipe(startWith(this.form.controls.make.value));
    const year$ = this.form.controls.year.valueChanges.pipe(startWith(this.form.controls.year.value));
    combineLatest([make$, year$])
      .pipe(
        debounceTime(300),
        filter(([make, year]) => this.tab() === 'catalog' && !!make && make.trim().length > 1 && !!year),
        distinctUntilChanged(([a, b], [c, d]) => a === c && b === d),
        tap(() => this.modelsLoading.set(true)),
        switchMap(([make, year]) => this.api.models(make.trim(), year!).pipe(catchError(() => of([] as CarModel[])))),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(models => {
        this.models.set(models);
        this.modelsLoading.set(false);
      });

    // All tabs: once year + make + model are known, offer the exact engine/gearbox versions
    const model$ = this.form.controls.model.valueChanges.pipe(startWith(this.form.controls.model.value));
    combineLatest([year$, make$, model$])
      .pipe(
        debounceTime(500),
        distinctUntilChanged(([a, b, c], [d, e, f]) => a === d && b === e && c === f),
        tap(() => { this.versions.set([]); this.form.controls.epa_id.setValue(null); }),
        filter(([year, make, model]) => !!year && year >= 1984 && make.trim().length > 1 && model.trim().length > 0),
        tap(() => this.versionsLoading.set(true)),
        switchMap(([year, make, model]) =>
          this.api.versions(make.trim(), model.trim(), year!).pipe(catchError(() => of([] as EpaVersion[])))),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(versions => {
        this.versions.set(versions);
        this.versionsLoading.set(false);
      });
  }

  /** Picking an exact version fills engine / gearbox / fuel; the backend stores its full specs. */
  pickVersion(id: number | null) {
    this.form.controls.epa_id.setValue(id);
    const v = this.versions().find(x => x.id === id);
    if (!v) return;
    this.form.patchValue({
      engine: engineFromVersion(v.text) || this.form.controls.engine.value,
      transmission: normalizeGearbox(v.text) || this.form.controls.transmission.value,
      ...(/hybrid/i.test(v.model + v.text) ? { fuel_type: 'hybrid' } : {}),
    });
  }

  vinSummary(r: VinDecode): string {
    return [r.trim, r.engine, r.body_class].filter(Boolean).join(' · ');
  }

  setTab(tab: VehicleSource) {
    this.tab.set(tab);
    this.error.set(null);
  }

  pickMake(name: string) {
    this.form.controls.make.setValue(name);
    this.form.controls.model.setValue('');
  }

  decodeVin() {
    const vin = this.vinCtrl.value.trim().toUpperCase();
    if (this.vinCtrl.invalid || !vin) return;
    this.vinBusy.set(true);
    this.error.set(null);
    this.vinResult.set(null);

    this.api.decodeVin(vin).subscribe({
      next: r => {
        this.vinBusy.set(false);
        this.vinResult.set(r);
        this.form.patchValue({
          year: r.year,
          make: r.make ?? '',
          model: r.model ?? '',
          trim: r.trim ?? '',
          engine: r.engine ?? '',
          fuel_type: normalizeFuel(r.fuel_type),
          transmission: normalizeGearbox(r.transmission),
        });
      },
      error: err => {
        this.vinBusy.set(false);
        this.error.set(apiError(err, this.i18n.t('add.notFound')));
      },
    });
  }

  /** Photo of the registration card -> VIN read by the AI -> same decode as a typed VIN. */
  async vinFromPhoto(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';  // allow picking the same file again after a failure
    if (!file) return;
    this.vinBusy.set(true);
    this.vinReading.set(true);
    this.error.set(null);
    this.vinResult.set(null);

    const done = () => {
      this.vinBusy.set(false);
      this.vinReading.set(false);
    };
    this.api.vinFromPhoto(await shrinkImage(file)).subscribe({
      next: ({ vin }) => {
        done();
        this.vinCtrl.setValue(vin);
        this.decodeVin();
      },
      error: err => {
        done();
        this.error.set(err?.status === 422
          ? this.i18n.t('add.vinPhotoFail')
          : apiError(err, this.i18n.t('add.vinPhotoFail')));
      },
    });
  }

  save() {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const vin = this.tab() === 'vin' ? this.vinResult()?.vin ?? null : null;

    this.saving.set(true);
    this.error.set(null);
    this.api
      .createVehicle({
        make: v.make.trim(),
        model: v.model.trim(),
        year: Number(v.year),
        trim: v.trim.trim() || null,
        engine: v.engine.trim() || null,
        fuel_type: v.fuel_type || null,
        transmission: v.transmission || null,
        mileage_km: v.mileage_km ?? null,
        nickname: v.nickname.trim() || null,
        vin,
        source: this.tab(),
        vin_data: this.tab() === 'vin' ? this.vinResult()?.raw ?? null : null,
        epa_id: v.epa_id,
      })
      .subscribe({
        // Straight to the chat: that's the point of adding the car
        next: car => this.router.navigate(['/cars', car.id, 'chat']),
        error: err => {
          this.saving.set(false);
          this.error.set(apiError(err, this.i18n.t('errors.generic')));
        },
      });
  }
}

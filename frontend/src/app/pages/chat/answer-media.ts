import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { PartFind, PartPhoto, RepairVideo, Vehicle } from '../../core/models';
import { AnswerMedia } from '../../shared/format';
import { TranslatePipe } from '../../shared/translate.pipe';

/**
 * Pictures under a mechanic answer, from the hidden media tag:
 * the factory diagram of this car's part with its OE number (17VIN, by VIN), else a generic part
 * photo (Wikimedia, credited) + "where is it on my car" image search
 * + PartSouq catalog for the VIN + repair video (embedded with a YouTube key, else a search link)
 * + a button to the car's own parts catalog (OE numbers by VIN) when the user asked to see the parts.
 * Nothing is copied: photos are free-licence, everything else stays on its own site.
 */
@Component({
  selector: 'app-answer-media',
  imports: [RouterLink, TranslatePipe],
  template: `
    <div class="media">
      @if (media().catalog && vehicle(); as v) {
        <a class="btn btn-accent catalog" [routerLink]="['/cars', v.id, 'parts']">🔩 {{ 'parts.open' | t }}</a>
      }
      @for (part of media().parts; track part) {
        <div class="part">
          @if (diagrams()[part]; as d) {
            @if (d.image) {
              <a class="diagram" [routerLink]="['/cars', vehicle()?.id, 'parts']" [title]="'parts.open' | t"
                 [queryParams]="{ section: d.section.code, level: d.section.level, name: d.section.name }">
                <img [src]="d.image" [alt]="part" loading="lazy" />
                @for (h of d.hotspots; track $index) {
                  <span class="spot" [style.left.%]="h.x" [style.top.%]="h.y"></span>
                }
              </a>
            }
          } @else if (photos()[part]; as p) {
            <a class="thumb" [href]="p.page_url" target="_blank" rel="noopener">
              <img [src]="p.thumb_url" [alt]="part" loading="lazy" />
            </a>
          }
          <div class="part-body">
            <strong dir="ltr">{{ part }}</strong>
            @if (diagrams()[part]; as d) {
              <small class="muted credit">{{ 'media.diagram' | t }} · <span dir="ltr">{{ d.section.name }}</span></small>
              @for (p of d.parts; track p.number) {
                <span class="oe" dir="ltr"><b>OE {{ p.number }}</b> · {{ p.name }}</span>
              }
            } @else if (photos()[part]; as p) {
              <small class="muted credit">
                {{ 'media.generic' | t }} ·
                <a [href]="p.page_url" target="_blank" rel="noopener">{{ p.author ?? 'Wikimedia' }}, {{ p.license }}</a>
              </small>
            }
            <div class="links">
              @if (diagrams()[part]; as d) {
                <a class="chip" [routerLink]="['/cars', vehicle()?.id, 'parts']"
                   [queryParams]="{ section: d.section.code, level: d.section.level, name: d.section.name }">🔩 {{ 'media.inCatalog' | t }}</a>
              }
              <a class="chip" [href]="whereUrl(part)" target="_blank" rel="noopener">📍 {{ 'media.where' | t }}</a>
              @if (vehicle()?.vin; as vin) {
                <a class="chip" [href]="partsouqUrl(vin)" target="_blank" rel="noopener">🛒 {{ 'media.partsouq' | t }}</a>
              }
            </div>
          </div>
        </div>
      }

      @if (media().video; as q) {
        @if (video(); as v) {
          <div class="video">
            <iframe [src]="v.embed" [title]="v.title" loading="lazy" allowfullscreen
                    allow="accelerometer; encrypted-media; gyroscope; picture-in-picture"></iframe>
            <small class="muted" dir="auto">▶ {{ v.title }}@if (v.channel) { — {{ v.channel }} }</small>
          </div>
        } @else {
          <a class="chip" [href]="youtubeSearchUrl(q)" target="_blank" rel="noopener">▶ {{ 'media.video' | t }}</a>
        }
      }
    </div>
  `,
  styles: `
    .media { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding-top: 12px;
      border-top: 1px dashed var(--line); }
    .catalog { align-self: flex-start; }
    .part { display: flex; gap: 10px; align-items: flex-start; padding: 10px; border-radius: 12px; background: #faf8f4;
      border: 1px solid var(--line); }
    .diagram { position: relative; flex: none; width: 150px; background: #fff; border: 1px solid var(--line);
      border-radius: 10px; padding: 4px; display: block; }
    .diagram img { width: 100%; display: block; }
    .spot { position: absolute; width: 7.5%; aspect-ratio: 2.6 / 1; border-radius: 2px;
      background: rgba(242, 163, 58, .55); outline: 1px solid var(--accent-ink); pointer-events: none; }
    .oe { font-size: .8rem; }
    .oe b { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    @media (max-width: 480px) { .part { flex-direction: column; } .diagram { width: 100%; max-width: 260px; } }
    .thumb img { width: 84px; height: 84px; object-fit: cover; border-radius: 10px; border: 1px solid var(--line);
      background: #fff; display: block; }
    .part-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
    .part-body strong { text-transform: capitalize; }
    .credit { font-size: .72rem; }
    .credit a { color: inherit; }
    .links { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { align-self: flex-start; font-size: .8rem; font-weight: 600; text-decoration: none; padding: 4px 10px;
      border-radius: 999px; border: 1px solid var(--line); background: var(--card); color: var(--ink); }
    .chip { transition: border-color .15s ease, background .15s ease; }
    .chip:hover { border-color: var(--ink-2); background: #fff; }
    .video { display: flex; flex-direction: column; gap: 4px; }
    .video iframe { width: 100%; max-width: 480px; aspect-ratio: 16 / 9; border: 0; border-radius: 10px; }
  `,
})
export class AnswerMediaComponent implements OnInit {
  private api = inject(ApiService);
  private sanitizer = inject(DomSanitizer);

  media = input.required<AnswerMedia>();
  vehicle = input<Vehicle | null>(null);

  protected photos = signal<Record<string, PartPhoto>>({});
  /** This car's factory diagram per part (only when the car has a VIN and the catalog knows the part). */
  protected diagrams = signal<Record<string, PartFind>>({});
  /** Embed URL built once (a new SafeResourceUrl on each render would reload the iframe). */
  protected video = signal<(RepairVideo & { embed: SafeResourceUrl }) | null>(null);

  // Fetched once: the parent re-parses messages on every update, but the tag of a message never changes
  ngOnInit() {
    const v = this.vehicle();
    for (const part of this.media().parts) {
      if (v?.vin) {
        this.api.findPart(v.id, part).subscribe({
          next: d => (d ? this.diagrams.update(all => ({ ...all, [part]: d })) : this.loadPhoto(part)),
          error: () => this.loadPhoto(part),
        });
      } else {
        this.loadPhoto(part);
      }
    }
    const q = this.media().video;
    if (q) {
      this.api.repairVideo(q).subscribe({
        next: v => this.video.set(v && { ...v, embed: this.embedUrl(v) }),
        error: () => {},
      });
    }
  }

  private loadPhoto(part: string) {
    this.api.partPhoto(part).subscribe({
      next: p => this.photos.update(all => ({ ...all, [part]: p })),
      error: () => {},  // no photo: the links are still shown
    });
  }

  private carName(): string {
    const v = this.vehicle();
    return v ? `${v.year} ${v.make} ${v.model}` : '';
  }

  whereUrl(part: string): string {
    const q = `${this.carName()} ${part} location`.trim();
    return `https://www.google.com/search?tbm=isch&q=${encodeURIComponent(q)}`;
  }

  partsouqUrl(vin: string): string {
    return `https://partsouq.com/en/search/all?q=${encodeURIComponent(vin)}`;
  }

  youtubeSearchUrl(q: string): string {
    return `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
  }

  private embedUrl(v: RepairVideo): SafeResourceUrl {
    // video_id comes from the YouTube API; still only allow its 11-char alphabet in a resource URL
    const id = /^[\w-]{11}$/.test(v.video_id) ? v.video_id : '';
    return this.sanitizer.bypassSecurityTrustResourceUrl(`https://www.youtube-nocookie.com/embed/${id}`);
  }
}

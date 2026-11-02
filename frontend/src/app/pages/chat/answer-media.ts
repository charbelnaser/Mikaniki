import { Component, OnInit, inject, input, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { PartPhoto, RepairVideo, Vehicle } from '../../core/models';
import { AnswerMedia } from '../../shared/format';
import { TranslatePipe } from '../../shared/translate.pipe';

/**
 * Pictures under a mechanic answer, from the hidden media tag:
 * generic part photo (Wikimedia, credited) + "where is it on my car" image search
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
          @if (photos()[part]; as p) {
            <a class="thumb" [href]="p.page_url" target="_blank" rel="noopener">
              <img [src]="p.thumb_url" [alt]="part" loading="lazy" />
            </a>
          }
          <div class="part-body">
            <strong dir="ltr">{{ part }}</strong>
            @if (photos()[part]; as p) {
              <small class="muted credit">
                {{ 'media.generic' | t }} ·
                <a [href]="p.page_url" target="_blank" rel="noopener">{{ p.author ?? 'Wikimedia' }}, {{ p.license }}</a>
              </small>
            }
            <div class="links">
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
  /** Embed URL built once (a new SafeResourceUrl on each render would reload the iframe). */
  protected video = signal<(RepairVideo & { embed: SafeResourceUrl }) | null>(null);

  // Fetched once: the parent re-parses messages on every update, but the tag of a message never changes
  ngOnInit() {
    for (const part of this.media().parts) {
      this.api.partPhoto(part).subscribe({
        next: p => this.photos.update(all => ({ ...all, [part]: p })),
        error: () => {},  // no photo: the links are still shown
      });
    }
    const q = this.media().video;
    if (q) {
      this.api.repairVideo(q).subscribe({
        next: v => this.video.set(v && { ...v, embed: this.embedUrl(v) }),
        error: () => {},
      });
    }
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

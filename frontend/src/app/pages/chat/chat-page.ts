import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Observable, of, switchMap } from 'rxjs';

import { ApiService, apiError } from '../../core/api.service';
import { I18nService } from '../../core/i18n.service';
import { ChatMessage, Conversation, Vehicle } from '../../core/models';
import { renderMarkdown, splitMedia } from '../../shared/format';
import { TranslatePipe } from '../../shared/translate.pipe';
import { AnswerMediaComponent } from './answer-media';

let tempId = -1;

@Component({
  selector: 'app-chat-page',
  imports: [RouterLink, TranslatePipe, AnswerMediaComponent],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.css',
})
export class ChatPage {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private i18n = inject(I18nService);

  private scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private fileInput = viewChild<ElementRef<HTMLInputElement>>('fileInput');

  protected vehicle = signal<Vehicle | null>(null);
  protected conversations = signal<Conversation[]>([]);
  protected conversationId = signal<number | null>(null);
  protected messages = signal<ChatMessage[]>([]);
  protected loading = signal(true);
  protected sending = signal(false);
  protected error = signal<string | null>(null);
  protected showHistory = signal(false);

  protected draft = signal('');
  protected image = signal<File | null>(null);
  protected imagePreview = signal<string | null>(null);

  protected readonly suggestions = ['chat.s1', 'chat.s2', 'chat.s3', 'chat.s4'];

  /** Assistant replies rendered once per message list: visible HTML + the hidden media tag. */
  protected answers = computed(() => new Map(
    this.messages()
      .filter(m => m.role === 'assistant' && !m.pending)
      .map(m => {
        const { text, media } = splitMedia(m.content);
        return [m.id, { html: renderMarkdown(text), media }] as const;
      }),
  ));

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe(params => {
      const vehicleId = Number(params.get('vehicleId'));
      const convParam = params.get('conversationId');
      const convId = convParam && convParam !== 'new' ? Number(convParam) : null;

      if (this.vehicle()?.id !== vehicleId) this.loadVehicle(vehicleId);
      // Skip reload when we just navigated to the conversation we created ourselves
      if (convId !== null && convId === this.conversationId()) return;
      this.openConversation(convId);
    });
  }

  // ---------------------------------------------------------------- loading
  private loadVehicle(id: number) {
    this.api.vehicle(id).subscribe({
      next: v => this.vehicle.set(v),
      error: () => this.router.navigateByUrl('/cars'),
    });
    this.api.conversations(id).subscribe(list => this.conversations.set(list));
  }

  private openConversation(id: number | null) {
    this.error.set(null);
    this.showHistory.set(false);
    this.conversationId.set(id);
    if (id === null) {
      this.messages.set([]);
      this.loading.set(false);
      return;
    }
    this.loading.set(true);
    this.api.conversation(id).subscribe({
      next: c => {
        this.messages.set(c.messages);
        this.loading.set(false);
        this.scrollToBottom();
      },
      error: () => {
        this.loading.set(false);
        this.newChat();
      },
    });
  }

  newChat() {
    const v = this.vehicle();
    if (v) this.router.navigate(['/cars', v.id, 'chat', 'new']);
    this.conversationId.set(null);
    this.messages.set([]);
    this.showHistory.set(false);
  }

  // ---------------------------------------------------------------- composer
  onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      this.send();
    }
  }

  onFile(event: Event) {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    this.clearImage();
    this.image.set(file);
    this.imagePreview.set(URL.createObjectURL(file));
  }

  clearImage() {
    const url = this.imagePreview();
    if (url) URL.revokeObjectURL(url);
    this.image.set(null);
    this.imagePreview.set(null);
    const input = this.fileInput()?.nativeElement;
    if (input) input.value = '';
  }

  useSuggestion(key: string) {
    this.send(this.i18n.t(key));
  }

  send(textOverride?: string) {
    const vehicle = this.vehicle();
    const text = (textOverride ?? this.draft()).trim();
    const image = this.image();
    if (!vehicle || this.sending() || (!text && !image)) return;

    this.sending.set(true);
    this.error.set(null);

    // Optimistic UI: show the user's message + a "thinking" bubble immediately
    const optimisticUser: ChatMessage = {
      id: tempId--, role: 'user', content: text, image_url: this.imagePreview(),
      created_at: new Date().toISOString(),
    };
    const thinking: ChatMessage = {
      id: tempId--, role: 'assistant', content: '', image_url: null,
      created_at: new Date().toISOString(), pending: true,
    };
    this.messages.update(list => [...list, optimisticUser, thinking]);
    this.draft.set('');
    // keep the object URL alive for the optimistic bubble; drop the File reference
    this.image.set(null);
    this.imagePreview.set(null);
    const input = this.fileInput()?.nativeElement;
    if (input) input.value = '';
    this.scrollToBottom();

    const conversation$: Observable<number> = this.conversationId() !== null
      ? of(this.conversationId()!)
      : this.api.createConversation(vehicle.id).pipe(switchMap(c => of(c.id)));

    conversation$
      .pipe(switchMap(convId => this.api.sendMessage(convId, text, image)))
      .subscribe({
        next: reply => {
          const isNew = this.conversationId() === null;
          this.conversationId.set(reply.conversation.id);
          this.messages.update(list => [
            ...list.filter(m => m.id !== optimisticUser.id && m.id !== thinking.id),
            reply.user_message,
            reply.assistant_message,
          ]);
          this.conversations.update(list => [
            reply.conversation,
            ...list.filter(c => c.id !== reply.conversation.id),
          ]);
          if (optimisticUser.image_url) URL.revokeObjectURL(optimisticUser.image_url);
          this.sending.set(false);
          this.scrollToBottom();
          if (isNew) {
            this.router.navigate(['/cars', vehicle.id, 'chat', reply.conversation.id], { replaceUrl: true });
          }
        },
        error: err => {
          // Roll back the optimistic bubbles and restore the draft + photo so the user can retry
          this.messages.update(list => list.filter(m => m.id !== thinking.id && m.id !== optimisticUser.id));
          this.error.set(apiError(err, this.i18n.t('errors.generic')));
          this.sending.set(false);
          this.draft.set(text);
          if (image) {
            this.image.set(image);
            this.imagePreview.set(optimisticUser.image_url);
          }
        },
      });
  }

  // ---------------------------------------------------------------- helpers

  private scrollToBottom() {
    setTimeout(() => {
      const el = this.scroller()?.nativeElement;
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    });
  }
}

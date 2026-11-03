import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  CarModel, ChatReply, Conversation, ConversationDetail, EpaVersion, Lang, Make, PartCategory, PartFind, PartList, PartPhoto, RepairVideo, WebImage,
  User, Vehicle, VehicleInput, VehicleReports, VinDecode,
} from './models';

/** Thin typed wrapper around the FastAPI backend (relative URLs: dev proxy / nginx in prod). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  // ---- auth
  register(body: { email: string; password: string; full_name?: string; language: Lang }) {
    return this.http.post<{ access_token: string }>('/api/auth/register', body);
  }
  login(body: { email: string; password: string }) {
    return this.http.post<{ access_token: string }>('/api/auth/login', body);
  }
  me() {
    return this.http.get<User>('/api/auth/me');
  }
  setLanguage(language: Lang) {
    return this.http.patch<User>('/api/auth/me/language', { language });
  }

  // ---- catalog
  makes() {
    return this.http.get<Make[]>('/api/catalog/makes');
  }
  models(make: string, year: number) {
    const params = new HttpParams().set('make', make).set('year', year);
    return this.http.get<CarModel[]>('/api/catalog/models', { params });
  }
  decodeVin(vin: string) {
    return this.http.get<VinDecode>(`/api/catalog/vin/${encodeURIComponent(vin)}`);
  }
  // ---- media under the mechanic's answers
  partPhoto(part: string) {
    return this.http.get<PartPhoto>('/api/media/part-photo', { params: new HttpParams().set('q', part) });
  }
  /** Web photos (empty when no image search provider is configured). */
  webImages(query: string) {
    return this.http.get<WebImage[]>('/api/media/images', { params: new HttpParams().set('q', query) });
  }
  repairVideo(query: string) {
    return this.http.get<RepairVideo | null>('/api/media/video', { params: new HttpParams().set('q', query) });
  }
  /** Read the VIN from a photo of the registration card / windshield plate. */
  vinFromPhoto(image: Blob) {
    const form = new FormData();
    form.append('image', image, 'vin.jpg');
    return this.http.post<{ vin: string }>('/api/catalog/vin-photo', form);
  }
  versions(make: string, model: string, year: number) {
    const params = new HttpParams().set('make', make).set('model', model).set('year', year);
    return this.http.get<EpaVersion[]>('/api/catalog/versions', { params });
  }

  // ---- vehicles
  vehicles() {
    return this.http.get<Vehicle[]>('/api/vehicles');
  }
  vehicle(id: number) {
    return this.http.get<Vehicle>(`/api/vehicles/${id}`);
  }
  createVehicle(body: VehicleInput) {
    return this.http.post<Vehicle>('/api/vehicles', body);
  }
  deleteVehicle(id: number) {
    return this.http.delete<void>(`/api/vehicles/${id}`);
  }
  vehicleReports(id: number) {
    return this.http.get<VehicleReports>(`/api/vehicles/${id}/reports`);
  }

  // ---- original parts catalog (by VIN)
  /** Top categories, or the sub-categories of `parent` (a category of level `parentLevel`). */
  partCategories(vehicleId: number, parent?: PartCategory) {
    const params = parent ? new HttpParams().set('parent', parent.code).set('parent_level', parent.level) : undefined;
    return this.http.get<PartCategory[]>(`/api/vehicles/${vehicleId}/parts/categories`, { params });
  }
  /** Diagram + OE numbers for a generic part name on this car (null when unknown). */
  findPart(vehicleId: number, part: string) {
    return this.http.get<PartFind | null>(`/api/vehicles/${vehicleId}/parts/find`, { params: new HttpParams().set('q', part) });
  }
  partList(vehicleId: number, category: PartCategory) {
    const params = new HttpParams().set('code', category.code).set('level', category.level);
    return this.http.get<PartList>(`/api/vehicles/${vehicleId}/parts`, { params });
  }

  // ---- chat
  conversations(vehicleId: number) {
    return this.http.get<Conversation[]>(`/api/vehicles/${vehicleId}/conversations`);
  }
  createConversation(vehicleId: number) {
    return this.http.post<Conversation>(`/api/vehicles/${vehicleId}/conversations`, {});
  }
  conversation(id: number) {
    return this.http.get<ConversationDetail>(`/api/conversations/${id}`);
  }
  deleteConversation(id: number) {
    return this.http.delete<void>(`/api/conversations/${id}`);
  }
  sendMessage(conversationId: number, text: string, image?: File | null): Observable<ChatReply> {
    const form = new FormData();
    form.append('text', text);
    if (image) form.append('image', image, image.name);
    return this.http.post<ChatReply>(`/api/conversations/${conversationId}/messages`, form);
  }
}

/** Extract a readable message from a FastAPI error response. */
export function apiError(err: unknown, fallback: string): string {
  const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  return fallback;
}

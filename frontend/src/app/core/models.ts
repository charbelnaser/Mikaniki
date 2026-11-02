export type Lang = 'ar' | 'en' | 'fr';

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  language: Lang;
}

export interface Make {
  id: number | null;
  name: string;
  popular: boolean;
}

export interface CarModel {
  id: number | null;
  name: string;
}

export interface VinDecode {
  vin: string;
  make: string | null;
  model: string | null;
  year: number | null;
  trim: string | null;
  engine: string | null;
  fuel_type: string | null;
  transmission: string | null;
  body_class: string | null;
  plant_country: string | null;
  raw: Record<string, unknown>;
  warnings: string[];
}

export type VehicleSource = 'catalog' | 'vin' | 'manual';

export interface VehicleInput {
  make: string;
  model: string;
  year: number;
  trim?: string | null;
  engine?: string | null;
  fuel_type?: string | null;
  transmission?: string | null;
  mileage_km?: number | null;
  vin?: string | null;
  nickname?: string | null;
  source: VehicleSource;
  vin_data?: Record<string, unknown> | null;
  /** Exact version from /api/catalog/versions; the backend fetches its specs. */
  epa_id?: number | null;
}

export interface Vehicle extends VehicleInput {
  id: number;
  display_name: string;
  specs: Record<string, string | number | boolean> | null;
  created_at: string;
}

/** Exact engine + gearbox version from FuelEconomy.gov (US EPA). */
export interface EpaVersion {
  id: number;
  text: string;
  model: string;
}

export interface SafetyRating {
  description: string;
  overall: string | null;
  frontal: string | null;
  side: string | null;
  rollover: string | null;
}

/** One recall from any market. Texts are in English, as published by the agency. */
export interface Recall {
  market: 'US' | 'CA' | 'UK';
  ref: string;
  date: string | null;
  component: string | null;
  summary: string | null;
  consequence: string | null;
  remedy: string | null;
  park_it: boolean;
}

export interface ComplaintComponent {
  component: string;
  count: number;
  examples: string[];
}

/** Recalls, owner complaints and crash-test stars for the car card. */
export interface VehicleReports {
  available: boolean;
  recalls_us: number;
  recalls_canada: number;
  recalls_uk: number;
  complaints: number;
  safety: SafetyRating | null;
  recalls: Recall[];
  top_components: ComplaintComponent[];
  crashes: number;
  fires: number;
  injuries: number;
}

/** Wikimedia Commons photo: author and licence must be displayed with it. */
export interface PartPhoto {
  thumb_url: string;
  page_url: string;
  author: string | null;
  license: string | null;
}

export interface RepairVideo {
  video_id: string;
  title: string;
  channel: string | null;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  image_url: string | null;
  created_at: string;
  pending?: boolean;
}

export interface Conversation {
  id: number;
  vehicle_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}

export interface ChatReply {
  conversation: Conversation;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

/** Original parts catalog (EPC) of a car, by VIN (backend routers/parts.py, 17VIN). */
export interface PartCategory {
  code: string;
  name: string;
  name_zh: string | null;
  remark: string | null;
  level: number;
  /** true: open its part list; false: open its sub-categories */
  is_last: boolean;
  /** false: in the EPC but not for this exact VIN */
  fits: boolean;
  image: string | null;
}

export interface PartItem {
  /** number on the diagram */
  callout: string | null;
  /** OE part number */
  number: string;
  name: string;
  name_zh: string | null;
  qty: string | null;
  remark: string | null;
  replacement: string | null;
  begin_date: string | null;
  end_date: string | null;
  fits: boolean;
}

/** Callout label position on the diagram, in % of its size. */
export interface Hotspot {
  callout: string;
  x: number;
  y: number;
}

/** Factory diagram of the catalog section matching a part named in a chat answer. */
export interface PartFind {
  section: { code: string; name: string; level: number };
  image: string | null;
  /** only the matched parts' callouts */
  hotspots: Hotspot[];
  parts: PartItem[];
}

export interface PartList {
  image: string | null;
  hotspots: Hotspot[];
  parts: PartItem[];
}

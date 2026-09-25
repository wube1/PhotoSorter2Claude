export type Status = "ready" | "review" | "duplicate" | "pending";

export interface Location {
  city?: string | null;
  place?: string | null;
  place_kind?: string;
  street?: string | null;
  display?: string | null;
  source?: "osm" | "custom";
}

export interface Card {
  id: number;
  name: string;
  path: string;
  size: number;
  taken_at: string | null;
  taken_source: "exif" | "mtime" | null;
  lat: number | null;
  lon: number | null;
  width: number | null;
  height: number | null;
  camera: string | null;
  doc_score: number | null;
  location: Location | null;
  auto_folder: string | null;
  manual_folder: string | null;
  approved: boolean;
  dup_of: number | null;
  folder: string;
  status: Status;
  reason: string;
  manual: boolean;
  thumb: string | null;
}

export interface Job {
  running: boolean;
  kind: "scan" | "move" | "delete" | null;
  phase: string;
  done: number;
  total: number;
  message: string;
  started_at: number | null;
  finished_at: number | null;
  result: Record<string, unknown> | null;
}

export interface Replacement {
  id: number;
  from_folder: string;
  to_folder: string;
  created_at: number;
}

export interface AppConfig {
  loaded: boolean;
  error: string | null;
  file: string;
  places: string[];
  geocoding: boolean;
  delete_mode: "permanent" | "trash";
  date_format: string;
  inbox: string;
  sorted: string;
}

export interface AppState {
  version: string;
  cards: Card[];
  replacements: Replacement[];
  predefined_folders: string[];
  job: Job;
  config: AppConfig;
}

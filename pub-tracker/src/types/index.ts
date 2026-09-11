// Core domain types for Dublin Pub Tracker.
// "Static" pub facts (name, coords, area…) live in src/data/pubs.json and are
// loaded read-only. Everything a user does — visits, ratings, photos, favourites —
// is user-generated data stored in IndexedDB (see src/db).

export type Person = 'harry' | 'ava';
export type PersonOrBoth = Person | 'both';

export interface Pub {
  id: string;
  name: string;
  lat: number;
  lon: number;
  area: string;
  district: string;
  region: string;
  address: string | null;
  phone: string | null;
  website: string | null;
  openingHours: string | null;
  tags: string[];
  image: string | null;
  source: string;
  googleMapsUrl: string;
  directionsUrl: string;
  createdAt: string;
}

/** User corrections layered on top of the read-only Pub record. */
export interface PubEdit {
  pubId: string;
  name?: string;
  area?: string;
  district?: string;
  address?: string;
  website?: string;
  phone?: string;
  notes?: string;
  imageOverride?: string; // data URL or remote URL supplied by the user
  updatedAt: string;
}

export interface DrinkPhoto {
  id: string;
  drinkId: string;
  blob: Blob;
  thumbBlob: Blob;
  createdAt: string;
}

export interface Drink {
  id: string;
  visitId: string;
  name: string;
  rating: number | null; // 0-5, half steps
  comment: string | null;
  createdAt: string;
}

export interface Visit {
  id: string;
  pubId: string;
  date: string; // ISO date (yyyy-mm-dd)
  time: string | null; // HH:mm
  who: PersonOrBoth;
  notes: string | null;
  createdAt: string;
}

export interface Review {
  pubId: string;
  person: Person;
  rating: number | null; // 0-5, half-star steps
  comment: string | null;
  updatedAt: string;
}

export interface PubStatus {
  pubId: string;
  visited: boolean;
  firstVisitDate: string | null;
  favouriteHarry: boolean;
  favouriteAva: boolean;
  wantToVisit: boolean;
  updatedAt: string;
}

export interface PubCrawlStop {
  pubId: string;
  order: number;
}

export interface PubCrawl {
  id: string;
  name: string;
  stops: PubCrawlStop[];
  createdAt: string;
  updatedAt: string;
}

export interface AppSettings {
  id: 'settings';
  hasSeenOnboarding: boolean;
  lastLocation: { lat: number; lon: number } | null;
}

export interface PubWithComputed extends Pub {
  status: PubStatus;
  edit: PubEdit | null;
  harryReview: Review | null;
  avaReview: Review | null;
  combinedRating: number | null;
  visitCount: number;
  distanceKm: number | null;
  displayName: string;
  displayArea: string;
  displayAddress: string | null;
  displayImage: string | null;
}

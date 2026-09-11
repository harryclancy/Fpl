import Dexie, { type Table } from 'dexie';
import type {
  AppSettings,
  Drink,
  DrinkPhoto,
  PubCrawl,
  PubEdit,
  PubStatus,
  Review,
  Visit,
} from '../types';

/**
 * All user-generated data lives here (IndexedDB via Dexie). Static pub facts
 * (name/coords/area) are NOT stored here — they're loaded read-only from
 * src/data/pubs.json — keeping "our data" cleanly separable for backup/export
 * and for a future cloud-sync layer to slot in without a schema change.
 */
export class PubTrackerDB extends Dexie {
  statuses!: Table<PubStatus, string>;
  reviews!: Table<Review, [string, string]>;
  visits!: Table<Visit, string>;
  drinks!: Table<Drink, string>;
  photos!: Table<DrinkPhoto, string>;
  edits!: Table<PubEdit, string>;
  crawls!: Table<PubCrawl, string>;
  settings!: Table<AppSettings, string>;

  constructor() {
    super('dublin-pub-tracker');
    this.version(1).stores({
      statuses: 'pubId, visited, favouriteHarry, favouriteAva, wantToVisit',
      reviews: '[pubId+person], pubId, person',
      visits: 'id, pubId, date',
      drinks: 'id, visitId',
      photos: 'id, drinkId, createdAt',
      edits: 'pubId',
      crawls: 'id, updatedAt',
      settings: 'id',
    });
  }
}

export const db = new PubTrackerDB();

export function emptyStatus(pubId: string): PubStatus {
  return {
    pubId,
    visited: false,
    firstVisitDate: null,
    favouriteHarry: false,
    favouriteAva: false,
    wantToVisit: false,
    updatedAt: new Date().toISOString(),
  };
}

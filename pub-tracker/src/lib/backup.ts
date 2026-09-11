import { db } from '../db/database';
import { blobToDataUrl, dataUrlToBlob } from './photos';
import type { AppSettings, Drink, DrinkPhoto, PubCrawl, PubEdit, PubStatus, Review, Visit } from '../types';

const BACKUP_VERSION = 1;

interface SerializedPhoto {
  id: string;
  drinkId: string;
  blob: string; // data URL
  thumbBlob: string; // data URL
  createdAt: string;
}

export interface BackupFile {
  version: number;
  exportedAt: string;
  app: 'dublin-pub-tracker';
  data: {
    statuses: PubStatus[];
    reviews: Review[];
    visits: Visit[];
    drinks: Drink[];
    photos: SerializedPhoto[];
    edits: PubEdit[];
    crawls: PubCrawl[];
    settings: AppSettings[];
  };
}

export async function exportBackup(): Promise<Blob> {
  const [statuses, reviews, visits, drinks, photos, edits, crawls, settings] = await Promise.all([
    db.statuses.toArray(),
    db.reviews.toArray(),
    db.visits.toArray(),
    db.drinks.toArray(),
    db.photos.toArray(),
    db.edits.toArray(),
    db.crawls.toArray(),
    db.settings.toArray(),
  ]);

  const serializedPhotos: SerializedPhoto[] = await Promise.all(
    photos.map(async (p) => ({
      id: p.id,
      drinkId: p.drinkId,
      blob: await blobToDataUrl(p.blob),
      thumbBlob: await blobToDataUrl(p.thumbBlob),
      createdAt: p.createdAt,
    }))
  );

  const backup: BackupFile = {
    version: BACKUP_VERSION,
    exportedAt: new Date().toISOString(),
    app: 'dublin-pub-tracker',
    data: { statuses, reviews, visits, drinks, photos: serializedPhotos, edits, crawls, settings },
  };

  return new Blob([JSON.stringify(backup)], { type: 'application/json' });
}

export function downloadBackup(blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `dublin-pub-tracker-backup-${stamp}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export interface BackupSummary {
  visits: number;
  drinks: number;
  photos: number;
  reviews: number;
  crawls: number;
  visitedPubs: number;
}

export function summarizeBackup(backup: BackupFile): BackupSummary {
  return {
    visits: backup.data.visits.length,
    drinks: backup.data.drinks.length,
    photos: backup.data.photos.length,
    reviews: backup.data.reviews.length,
    crawls: backup.data.crawls.length,
    visitedPubs: backup.data.statuses.filter((s) => s.visited).length,
  };
}

export async function parseBackupFile(file: File): Promise<BackupFile> {
  const text = await file.text();
  const parsed = JSON.parse(text);
  if (parsed.app !== 'dublin-pub-tracker' || !parsed.data) {
    throw new Error('This file does not look like a Dublin Pub Tracker backup.');
  }
  return parsed as BackupFile;
}

/** Replaces all local user data with the contents of the backup. Destructive — the
 * caller (Settings screen) is responsible for confirming with the user first. */
export async function importBackup(backup: BackupFile): Promise<void> {
  const photos: DrinkPhoto[] = await Promise.all(
    backup.data.photos.map(async (p) => ({
      id: p.id,
      drinkId: p.drinkId,
      blob: await dataUrlToBlob(p.blob),
      thumbBlob: await dataUrlToBlob(p.thumbBlob),
      createdAt: p.createdAt,
    }))
  );

  await db.transaction(
    'rw',
    [db.statuses, db.reviews, db.visits, db.drinks, db.photos, db.edits, db.crawls, db.settings],
    async () => {
      await Promise.all([
        db.statuses.clear(),
        db.reviews.clear(),
        db.visits.clear(),
        db.drinks.clear(),
        db.photos.clear(),
        db.edits.clear(),
        db.crawls.clear(),
        db.settings.clear(),
      ]);
      await Promise.all([
        db.statuses.bulkPut(backup.data.statuses),
        db.reviews.bulkPut(backup.data.reviews),
        db.visits.bulkPut(backup.data.visits),
        db.drinks.bulkPut(backup.data.drinks),
        db.photos.bulkPut(photos),
        db.edits.bulkPut(backup.data.edits),
        db.crawls.bulkPut(backup.data.crawls),
        db.settings.bulkPut(backup.data.settings),
      ]);
    }
  );
}

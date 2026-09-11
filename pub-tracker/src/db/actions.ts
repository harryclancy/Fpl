import { db, emptyStatus } from './database';
import { newId } from '../lib/id';
import { compressForStorage, makeThumbnail } from '../lib/photos';
import type { Person, PersonOrBoth, PubEdit, PubStatus, Review, Visit } from '../types';

export async function getStatus(pubId: string): Promise<PubStatus> {
  const existing = await db.statuses.get(pubId);
  return existing ?? emptyStatus(pubId);
}

async function ensureStatus(pubId: string): Promise<PubStatus> {
  const existing = await db.statuses.get(pubId);
  if (existing) return existing;
  const fresh = emptyStatus(pubId);
  await db.statuses.put(fresh);
  return fresh;
}

export async function setVisited(pubId: string, visited: boolean, date?: string): Promise<void> {
  const status = await ensureStatus(pubId);
  const next: PubStatus = {
    ...status,
    visited,
    firstVisitDate: visited ? status.firstVisitDate ?? date ?? new Date().toISOString().slice(0, 10) : status.firstVisitDate,
    updatedAt: new Date().toISOString(),
  };
  await db.statuses.put(next);
}

export async function toggleFavourite(pubId: string, person: Person): Promise<void> {
  const status = await ensureStatus(pubId);
  const key = person === 'harry' ? 'favouriteHarry' : 'favouriteAva';
  await db.statuses.put({ ...status, [key]: !status[key], updatedAt: new Date().toISOString() });
}

export async function toggleWantToVisit(pubId: string): Promise<void> {
  const status = await ensureStatus(pubId);
  await db.statuses.put({ ...status, wantToVisit: !status.wantToVisit, updatedAt: new Date().toISOString() });
}

export async function upsertReview(pubId: string, person: Person, rating: number | null, comment: string | null): Promise<void> {
  const review: Review = { pubId, person, rating, comment, updatedAt: new Date().toISOString() };
  await db.reviews.put(review);
}

export interface NewVisitInput {
  pubId: string;
  date: string;
  time: string | null;
  who: PersonOrBoth;
  notes: string | null;
}

export async function addVisit(input: NewVisitInput): Promise<Visit> {
  const visit: Visit = {
    id: newId(),
    pubId: input.pubId,
    date: input.date,
    time: input.time,
    who: input.who,
    notes: input.notes,
    createdAt: new Date().toISOString(),
  };
  await db.visits.put(visit);

  const status = await ensureStatus(input.pubId);
  if (!status.visited || !status.firstVisitDate || input.date < status.firstVisitDate) {
    await db.statuses.put({
      ...status,
      visited: true,
      firstVisitDate: !status.firstVisitDate || input.date < status.firstVisitDate ? input.date : status.firstVisitDate,
      updatedAt: new Date().toISOString(),
    });
  }
  return visit;
}

export async function updateVisit(id: string, changes: Partial<NewVisitInput>): Promise<void> {
  await db.visits.update(id, changes);
}

export async function deleteVisit(id: string): Promise<void> {
  const drinks = await db.drinks.where('visitId').equals(id).toArray();
  for (const d of drinks) {
    await deleteDrink(d.id);
  }
  await db.visits.delete(id);
}

export interface NewDrinkInput {
  visitId: string;
  name: string;
  rating: number | null;
  comment: string | null;
  photos: File[];
}

export async function addDrink(input: NewDrinkInput): Promise<string> {
  const drinkId = newId();
  await db.drinks.put({
    id: drinkId,
    visitId: input.visitId,
    name: input.name,
    rating: input.rating,
    comment: input.comment,
    createdAt: new Date().toISOString(),
  });

  for (const file of input.photos) {
    await addPhotoToDrink(drinkId, file);
  }

  return drinkId;
}

export async function addPhotoToDrink(drinkId: string, file: File | Blob): Promise<void> {
  const [full, thumb] = await Promise.all([compressForStorage(file), makeThumbnail(file)]);
  await db.photos.put({
    id: newId(),
    drinkId,
    blob: full,
    thumbBlob: thumb,
    createdAt: new Date().toISOString(),
  });
}

export async function deletePhoto(id: string): Promise<void> {
  await db.photos.delete(id);
}

export async function updateDrink(id: string, changes: Partial<Pick<import('../types').Drink, 'name' | 'rating' | 'comment'>>): Promise<void> {
  await db.drinks.update(id, changes);
}

export async function deleteDrink(id: string): Promise<void> {
  const photos = await db.photos.where('drinkId').equals(id).toArray();
  await db.photos.bulkDelete(photos.map((p) => p.id));
  await db.drinks.delete(id);
}

export async function upsertPubEdit(pubId: string, changes: Partial<Omit<PubEdit, 'pubId' | 'updatedAt'>>): Promise<void> {
  const existing = await db.edits.get(pubId);
  const next: PubEdit = {
    pubId,
    ...existing,
    ...changes,
    updatedAt: new Date().toISOString(),
  };
  await db.edits.put(next);
}

export async function createCrawl(name: string, pubIds: string[]): Promise<string> {
  const id = newId();
  await db.crawls.put({
    id,
    name,
    stops: pubIds.map((pubId, i) => ({ pubId, order: i })),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });
  return id;
}

export async function updateCrawlStops(id: string, pubIds: string[]): Promise<void> {
  const crawl = await db.crawls.get(id);
  if (!crawl) return;
  await db.crawls.put({
    ...crawl,
    stops: pubIds.map((pubId, i) => ({ pubId, order: i })),
    updatedAt: new Date().toISOString(),
  });
}

export async function renameCrawl(id: string, name: string): Promise<void> {
  await db.crawls.update(id, { name, updatedAt: new Date().toISOString() });
}

export async function deleteCrawl(id: string): Promise<void> {
  await db.crawls.delete(id);
}

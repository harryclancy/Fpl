import { useLiveQuery } from 'dexie-react-hooks';
import { db } from '../db/database';
import type { DrinkPhoto } from '../types';

export interface RecentPhoto extends DrinkPhoto {
  drinkName: string;
  pubId: string;
}

export function useRecentPhotos(limit = 8): RecentPhoto[] | undefined {
  return useLiveQuery(async () => {
    const photos = await db.photos.orderBy('createdAt').reverse().limit(limit).toArray();
    const drinkIds = [...new Set(photos.map((p) => p.drinkId))];
    const drinks = await db.drinks.bulkGet(drinkIds);
    const drinkMap = new Map(drinks.filter(Boolean).map((d) => [d!.id, d!]));
    const visitIds = [...new Set([...drinkMap.values()].map((d) => d.visitId))];
    const visits = await db.visits.bulkGet(visitIds);
    const visitMap = new Map(visits.filter(Boolean).map((v) => [v!.id, v!]));

    return photos
      .map((p) => {
        const drink = drinkMap.get(p.drinkId);
        const visit = drink ? visitMap.get(drink.visitId) : undefined;
        if (!drink || !visit) return null;
        return { ...p, drinkName: drink.name, pubId: visit.pubId };
      })
      .filter((x): x is RecentPhoto => x !== null);
  }, [limit]);
}

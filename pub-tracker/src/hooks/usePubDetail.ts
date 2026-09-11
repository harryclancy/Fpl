import { useLiveQuery } from 'dexie-react-hooks';
import { db } from '../db/database';
import type { Drink, DrinkPhoto, Visit } from '../types';

export interface VisitWithDrinks extends Visit {
  drinks: (Drink & { photos: DrinkPhoto[] })[];
}

export function useVisitsForPub(pubId: string | undefined): VisitWithDrinks[] | undefined {
  return useLiveQuery(async () => {
    if (!pubId) return [];
    const visits = await db.visits.where('pubId').equals(pubId).toArray();
    visits.sort((a, b) => (a.date + (a.time ?? '')).localeCompare(b.date + (b.time ?? '')));
    visits.reverse();

    const result: VisitWithDrinks[] = [];
    for (const visit of visits) {
      const drinks = await db.drinks.where('visitId').equals(visit.id).toArray();
      const drinksWithPhotos = await Promise.all(
        drinks.map(async (drink) => ({
          ...drink,
          photos: await db.photos.where('drinkId').equals(drink.id).toArray(),
        }))
      );
      result.push({ ...visit, drinks: drinksWithPhotos });
    }
    return result;
  }, [pubId]);
}

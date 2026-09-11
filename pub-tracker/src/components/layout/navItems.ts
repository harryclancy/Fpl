import type { LucideIcon } from 'lucide-react';
import { Beer, Heart, Home, ListChecks, Map, Route, Settings, Star, Bookmark } from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export const PRIMARY_NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/map', label: 'Map', icon: Map },
  { to: '/pubs', label: 'All Pubs', icon: Beer },
  { to: '/visited', label: 'Visited', icon: ListChecks },
];

export const SECONDARY_NAV: NavItem[] = [
  { to: '/want-to-visit', label: 'Want to Visit', icon: Bookmark },
  { to: '/favourites', label: 'Favourites', icon: Heart },
  { to: '/stats', label: 'Stats', icon: Star },
  { to: '/crawls', label: 'Pub Crawls', icon: Route },
  { to: '/settings', label: 'Settings & Backup', icon: Settings },
];

export const ALL_NAV: NavItem[] = [...PRIMARY_NAV, ...SECONDARY_NAV];

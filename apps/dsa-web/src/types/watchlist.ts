export type WatchlistMarket = 'cn' | 'hk' | 'us';
export type WatchlistSecurityType = 'stock' | 'etf' | 'option' | 'index' | 'fund' | 'other';
export type WatchlistRelationType = 'underlying' | 'tracks' | 'related_to';

export interface WatchlistRelation {
  id: number;
  sourceItemId: number;
  targetItemId: number;
  relationType: WatchlistRelationType;
  targetSymbol?: string | null;
  targetName?: string | null;
  targetMarket?: WatchlistMarket | null;
  targetSecurityType?: WatchlistSecurityType | null;
}

export interface WatchlistItem {
  id: number;
  symbol: string;
  name?: string | null;
  market?: WatchlistMarket | null;
  securityType: WatchlistSecurityType;
  active: boolean;
  sectorTags: string[];
  conceptTags: string[];
  customTags: string[];
  notes?: string | null;
  source?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  relations: WatchlistRelation[];
}

export interface WatchlistListResponse {
  total: number;
  items: WatchlistItem[];
}

export interface WatchlistItemInput {
  symbol: string;
  name?: string | null;
  market?: WatchlistMarket | null;
  securityType?: WatchlistSecurityType | null;
  active?: boolean;
  sectorTags?: string[];
  conceptTags?: string[];
  customTags?: string[];
  notes?: string | null;
}

import apiClient from './index';
import type {
  WatchlistItem,
  WatchlistItemInput,
  WatchlistListResponse,
  WatchlistRelation,
  WatchlistRelationType,
} from '../types/watchlist';

export type ExtractItem = {
  code?: string | null;
  name?: string | null;
  confidence: string;
};

export type ExtractFromImageResponse = {
  codes: string[];
  items?: ExtractItem[];
  rawText?: string;
};

export const stocksApi = {
  async extractFromImage(file: File): Promise<ExtractFromImageResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post(
      '/api/v1/stocks/extract-from-image',
      formData,
      {
        headers,
        timeout: 60000, // Vision API can be slow; 60s
      },
    );

    const data = response.data as { codes?: string[]; items?: ExtractItem[]; raw_text?: string };
    return {
      codes: data.codes ?? [],
      items: data.items,
      rawText: data.raw_text,
    };
  },

  async parseImport(file?: File, text?: string): Promise<ExtractFromImageResponse> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
      const response = await apiClient.post('/api/v1/stocks/parse-import', formData, { headers });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    if (text) {
      const response = await apiClient.post('/api/v1/stocks/parse-import', { text });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    throw new Error('请提供文件或粘贴文本');
  },

  async getWatchlist(params?: {
    activeOnly?: boolean;
    analyzableOnly?: boolean;
    market?: string;
    securityType?: string;
    tag?: string;
  }): Promise<WatchlistListResponse> {
    const response = await apiClient.get('/api/v1/stocks/watchlist', {
      params: {
        active_only: params?.activeOnly,
        analyzable_only: params?.analyzableOnly,
        market: params?.market,
        security_type: params?.securityType,
        tag: params?.tag,
      },
    });
    const data = response.data as {
      total: number;
      items: Array<Record<string, unknown>>;
    };
    return {
      total: data.total ?? 0,
      items: (data.items ?? []).map(mapWatchlistItem),
    };
  },

  async createWatchlistItem(payload: WatchlistItemInput): Promise<WatchlistItem> {
    const response = await apiClient.post('/api/v1/stocks/watchlist', serializeWatchlistItemInput(payload));
    return mapWatchlistItem(response.data as Record<string, unknown>);
  },

  async updateWatchlistItem(id: number, payload: WatchlistItemInput): Promise<WatchlistItem> {
    const response = await apiClient.put(`/api/v1/stocks/watchlist/${id}`, serializeWatchlistItemInput(payload));
    return mapWatchlistItem(response.data as Record<string, unknown>);
  },

  async setWatchlistItemActive(id: number, active: boolean): Promise<WatchlistItem> {
    const response = await apiClient.post(`/api/v1/stocks/watchlist/${id}/active`, undefined, {
      params: { active },
    });
    return mapWatchlistItem(response.data as Record<string, unknown>);
  },

  async deleteWatchlistItem(id: number): Promise<void> {
    await apiClient.delete(`/api/v1/stocks/watchlist/${id}`);
  },

  async createWatchlistRelation(input: {
    sourceItemId: number;
    targetItemId: number;
    relationType: WatchlistRelationType;
  }): Promise<WatchlistRelation> {
    const response = await apiClient.post('/api/v1/stocks/watchlist/relations', {
      source_item_id: input.sourceItemId,
      target_item_id: input.targetItemId,
      relation_type: input.relationType,
    });
    return mapWatchlistRelation(response.data as Record<string, unknown>);
  },

  async deleteWatchlistRelation(id: number): Promise<void> {
    await apiClient.delete(`/api/v1/stocks/watchlist/relations/${id}`);
  },

  async importWatchlistFromStockList(): Promise<WatchlistListResponse & { importedCount: number }> {
    const response = await apiClient.post('/api/v1/stocks/watchlist/import-stock-list');
    const data = response.data as { imported_count?: number; items?: Array<Record<string, unknown>> };
    return {
      importedCount: data.imported_count ?? 0,
      total: (data.items ?? []).length,
      items: (data.items ?? []).map(mapWatchlistItem),
    };
  },
};

function serializeWatchlistItemInput(payload: WatchlistItemInput): Record<string, unknown> {
  const result: Record<string, unknown> = {
    symbol: payload.symbol,
    name: payload.name ?? null,
    market: payload.market ?? null,
    security_type: payload.securityType ?? null,
    active: payload.active ?? true,
    notes: payload.notes ?? null,
  };
  if (payload.sectorTags !== undefined) result.sector_tags = payload.sectorTags;
  if (payload.conceptTags !== undefined) result.concept_tags = payload.conceptTags;
  if (payload.customTags !== undefined) result.custom_tags = payload.customTags;
  return result;
}

function mapWatchlistRelation(data: Record<string, unknown>): WatchlistRelation {
  return {
    id: Number(data.id ?? 0),
    sourceItemId: Number(data.source_item_id ?? 0),
    targetItemId: Number(data.target_item_id ?? 0),
    relationType: String(data.relation_type ?? 'related_to') as WatchlistRelationType,
    targetSymbol: (data.target_symbol as string | null | undefined) ?? null,
    targetName: (data.target_name as string | null | undefined) ?? null,
    targetMarket: (data.target_market as WatchlistRelation['targetMarket']) ?? null,
    targetSecurityType: (data.target_security_type as WatchlistRelation['targetSecurityType']) ?? null,
  };
}

function mapWatchlistItem(data: Record<string, unknown>): WatchlistItem {
  return {
    id: Number(data.id ?? 0),
    symbol: String(data.symbol ?? ''),
    name: (data.name as string | null | undefined) ?? null,
    market: (data.market as WatchlistItem['market']) ?? null,
    securityType: String(data.security_type ?? 'other') as WatchlistItem['securityType'],
    active: Boolean(data.active),
    sectorTags: Array.isArray(data.sector_tags) ? data.sector_tags.map(String) : [],
    conceptTags: Array.isArray(data.concept_tags) ? data.concept_tags.map(String) : [],
    customTags: Array.isArray(data.custom_tags) ? data.custom_tags.map(String) : [],
    notes: (data.notes as string | null | undefined) ?? null,
    source: (data.source as string | null | undefined) ?? null,
    createdAt: (data.created_at as string | null | undefined) ?? null,
    updatedAt: (data.updated_at as string | null | undefined) ?? null,
    relations: Array.isArray(data.relations)
      ? data.relations.map((item) => mapWatchlistRelation(item as Record<string, unknown>))
      : [],
  };
}

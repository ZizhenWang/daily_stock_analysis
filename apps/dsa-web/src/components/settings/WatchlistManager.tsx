import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { getParsedApiError } from '../../api/error';
import { stocksApi } from '../../api/stocks';
import type { WatchlistItem, WatchlistItemInput, WatchlistRelationType } from '../../types/watchlist';

interface WatchlistManagerProps {
  disabled?: boolean;
}

type DraftState = {
  id?: number;
  symbol: string;
  name: string;
  market: '' | 'cn' | 'hk' | 'us';
  securityType: 'stock' | 'etf' | 'option' | 'index' | 'fund' | 'other';
  active: boolean;
  sectorTags: string;
  conceptTags: string;
  customTags: string;
  notes: string;
};

const EMPTY_DRAFT: DraftState = {
  symbol: '',
  name: '',
  market: '',
  securityType: 'stock',
  active: true,
  sectorTags: '',
  conceptTags: '',
  customTags: '',
  notes: '',
};

function csvToTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function tagsToCsv(tags: string[]): string {
  return tags.join(', ');
}

function itemToDraft(item: WatchlistItem): DraftState {
  return {
    id: item.id,
    symbol: item.symbol,
    name: item.name ?? '',
    market: item.market ?? '',
    securityType: item.securityType,
    active: item.active,
    sectorTags: tagsToCsv(item.sectorTags),
    conceptTags: tagsToCsv(item.conceptTags),
    customTags: tagsToCsv(item.customTags),
    notes: item.notes ?? '',
  };
}

function draftToPayload(draft: DraftState): WatchlistItemInput {
  return {
    symbol: draft.symbol.trim(),
    name: draft.name.trim() || null,
    market: draft.market || null,
    securityType: draft.securityType,
    active: draft.active,
    sectorTags: csvToTags(draft.sectorTags),
    conceptTags: csvToTags(draft.conceptTags),
    customTags: csvToTags(draft.customTags),
    notes: draft.notes.trim() || null,
  };
}

export const WatchlistManager: React.FC<WatchlistManagerProps> = ({ disabled }) => {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [filterMarket, setFilterMarket] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterTag, setFilterTag] = useState('');
  const [relationTargetId, setRelationTargetId] = useState<number | ''>('');
  const [relationType, setRelationType] = useState<WatchlistRelationType>('related_to');

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await stocksApi.getWatchlist();
      setItems(response.items);
    } catch (e) {
      const parsed = getParsedApiError(e);
      setError(parsed.message || '加载 Watchlist 失败');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (filterMarket && item.market !== filterMarket) return false;
      if (filterType && item.securityType !== filterType) return false;
      if (filterTag) {
        const allTags = [...item.sectorTags, ...item.conceptTags, ...item.customTags];
        if (!allTags.some((tag) => tag.includes(filterTag.trim()))) return false;
      }
      return true;
    });
  }, [filterMarket, filterTag, filterType, items]);

  const relationCandidates = useMemo(
    () => items.filter((item) => item.id !== draft.id),
    [draft.id, items],
  );

  const handleSave = async () => {
    if (!draft.symbol.trim()) {
      setError('请输入代码');
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      if (draft.id) {
        await stocksApi.updateWatchlistItem(draft.id, draftToPayload(draft));
      } else {
        await stocksApi.createWatchlistItem(draftToPayload(draft));
      }
      setDraft(EMPTY_DRAFT);
      await load();
    } catch (e) {
      const parsed = getParsedApiError(e);
      setError(parsed.message || '保存失败');
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggleActive = async (item: WatchlistItem) => {
    try {
      await stocksApi.setWatchlistItemActive(item.id, !item.active);
      await load();
    } catch (e) {
      const parsed = getParsedApiError(e);
      setError(parsed.message || '更新状态失败');
    }
  };

  const handleDelete = async (item: WatchlistItem) => {
    if (!window.confirm(`确认删除 ${item.symbol} 吗？`)) return;
    try {
      await stocksApi.deleteWatchlistItem(item.id);
      if (draft.id === item.id) {
        setDraft(EMPTY_DRAFT);
      }
      await load();
    } catch (e) {
      const parsed = getParsedApiError(e);
      setError(parsed.message || '删除失败');
    }
  };

  const handleImportLegacy = async () => {
    try {
      const result = await stocksApi.importWatchlistFromStockList();
      setItems(result.items);
      setError(result.importedCount > 0 ? null : '未导入新标的，可能 watchlist 已存在数据');
    } catch (e) {
      const parsed = getParsedApiError(e);
      setError(parsed.message || '导入失败');
    }
  };

  const handleCreateRelation = async () => {
    if (!draft.id || relationTargetId === '') {
      setError('请先保存当前标的，再选择关联对象');
      return;
    }
    try {
      await stocksApi.createWatchlistRelation({
        sourceItemId: draft.id,
        targetItemId: relationTargetId,
        relationType,
      });
      setRelationTargetId('');
      await load();
      const refreshed = items.find((item) => item.id === draft.id);
      if (refreshed) {
        setDraft(itemToDraft(refreshed));
      }
    } catch (e) {
      const parsed = getParsedApiError(e);
      setError(parsed.message || '创建关联失败');
    }
  };

  const handleDeleteRelation = async (relationId: number) => {
    try {
      await stocksApi.deleteWatchlistRelation(relationId);
      await load();
    } catch (e) {
      const parsed = getParsedApiError(e);
      setError(parsed.message || '删除关联失败');
    }
  };

  const activeCount = items.filter((item) => item.active).length;

  return (
    <div className="space-y-4 rounded-xl border border-white/8 bg-elevated/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-white">Watchlist 管理</p>
          <p className="text-xs text-muted">数据库主导的结构化标的池。默认分析只会读取 active 且可分析的正股/ETF。</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn-secondary text-sm" onClick={() => void load()} disabled={disabled || isLoading}>
            刷新
          </button>
          <button type="button" className="btn-secondary text-sm" onClick={() => void handleImportLegacy()} disabled={disabled || isLoading}>
            导入旧 STOCK_LIST
          </button>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr]">
        <div className="rounded-xl border border-white/8 bg-card/40 p-3">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-secondary">
            <span>总数 {items.length}</span>
            <span>启用 {activeCount}</span>
          </div>
          <div className="mb-3 grid gap-2 md:grid-cols-3">
            <input
              className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white"
              placeholder="按标签筛选"
              value={filterTag}
              onChange={(e) => setFilterTag(e.target.value)}
            />
            <select className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" value={filterMarket} onChange={(e) => setFilterMarket(e.target.value)}>
              <option value="">全部市场</option>
              <option value="cn">A股</option>
              <option value="hk">港股</option>
              <option value="us">美股</option>
            </select>
            <select className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
              <option value="">全部类型</option>
              <option value="stock">正股</option>
              <option value="etf">ETF</option>
              <option value="option">期权</option>
              <option value="index">指数</option>
              <option value="fund">基金</option>
              <option value="other">其他</option>
            </select>
          </div>

          <div className="max-h-[480px] overflow-auto rounded-lg border border-white/8">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-card/80 text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2">市场/类型</th>
                  <th className="px-3 py-2">标签</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => (
                  <tr key={item.id} className="border-t border-white/8 text-secondary">
                    <td className="px-3 py-2">
                      <div className="font-medium text-white">{item.symbol}</div>
                      {item.name ? <div className="text-xs text-muted">{item.name}</div> : null}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {(item.market ?? '-').toUpperCase()} / {item.securityType.toUpperCase()}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {[...item.sectorTags, ...item.conceptTags, ...item.customTags].slice(0, 4).join(' / ') || '-'}
                    </td>
                    <td className="px-3 py-2">
                      <button type="button" className={`rounded-full px-2 py-1 text-xs ${item.active ? 'bg-emerald-500/20 text-emerald-300' : 'bg-white/8 text-muted'}`} onClick={() => void handleToggleActive(item)} disabled={disabled}>
                        {item.active ? '启用' : '停用'}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-2 text-xs">
                        <button type="button" className="text-cyan-300 hover:text-white" onClick={() => setDraft(itemToDraft(item))}>
                          编辑
                        </button>
                        <button type="button" className="text-red-300 hover:text-white" onClick={() => void handleDelete(item)} disabled={disabled}>
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!filteredItems.length ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-sm text-muted">
                      {isLoading ? '加载中...' : '暂无标的'}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-xl border border-white/8 bg-card/40 p-3">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-medium text-white">{draft.id ? '编辑标的' : '新增标的'}</p>
            {draft.id ? (
              <button type="button" className="text-xs text-muted hover:text-white" onClick={() => setDraft(EMPTY_DRAFT)}>
                新建一条
              </button>
            ) : null}
          </div>

          <div className="grid gap-2">
            <input className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" placeholder="代码，如 AAPL / hk00700 / 510300" value={draft.symbol} onChange={(e) => setDraft((prev) => ({ ...prev, symbol: e.target.value.toUpperCase() }))} />
            <input className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" placeholder="名称（可留空自动补）" value={draft.name} onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))} />
            <div className="grid gap-2 md:grid-cols-2">
              <select className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" value={draft.market} onChange={(e) => setDraft((prev) => ({ ...prev, market: e.target.value as DraftState['market'] }))}>
                <option value="">自动识别</option>
                <option value="cn">A股</option>
                <option value="hk">港股</option>
                <option value="us">美股</option>
              </select>
              <select className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" value={draft.securityType} onChange={(e) => setDraft((prev) => ({ ...prev, securityType: e.target.value as DraftState['securityType'] }))}>
                <option value="stock">正股</option>
                <option value="etf">ETF</option>
                <option value="option">期权</option>
                <option value="index">指数</option>
                <option value="fund">基金</option>
                <option value="other">其他</option>
              </select>
            </div>
            <label className="flex items-center gap-2 text-sm text-secondary">
              <input type="checkbox" checked={draft.active} onChange={(e) => setDraft((prev) => ({ ...prev, active: e.target.checked }))} />
              默认分析启用
            </label>
            <input className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" placeholder="领域标签，如 AI, 半导体" value={draft.sectorTags} onChange={(e) => setDraft((prev) => ({ ...prev, sectorTags: e.target.value }))} />
            <input className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" placeholder="概念标签，如 果链, 航天" value={draft.conceptTags} onChange={(e) => setDraft((prev) => ({ ...prev, conceptTags: e.target.value }))} />
            <input className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" placeholder="自定义标签" value={draft.customTags} onChange={(e) => setDraft((prev) => ({ ...prev, customTags: e.target.value }))} />
            <textarea className="min-h-[72px] rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" placeholder="备注" value={draft.notes} onChange={(e) => setDraft((prev) => ({ ...prev, notes: e.target.value }))} />
          </div>

          <div className="mt-3 flex gap-2">
            <button type="button" className="btn-primary" onClick={() => void handleSave()} disabled={disabled || isSaving}>
              {isSaving ? '保存中...' : draft.id ? '保存修改' : '新增标的'}
            </button>
            <button type="button" className="btn-secondary" onClick={() => setDraft(EMPTY_DRAFT)} disabled={disabled || isSaving}>
              重置
            </button>
          </div>

          {draft.id ? (
            <div className="mt-4 space-y-3 rounded-lg border border-white/8 bg-card/50 p-3">
              <p className="text-sm font-medium text-white">关联标的</p>
              <div className="grid gap-2 md:grid-cols-[1fr_140px_auto]">
                <select className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" value={relationTargetId} onChange={(e) => setRelationTargetId(e.target.value ? Number(e.target.value) : '')}>
                  <option value="">选择关联对象</option>
                  {relationCandidates.map((item) => (
                    <option key={item.id} value={item.id}>{item.symbol} {item.name ? `(${item.name})` : ''}</option>
                  ))}
                </select>
                <select className="rounded-lg border border-white/16 bg-card/60 px-2 py-2 text-sm text-white" value={relationType} onChange={(e) => setRelationType(e.target.value as WatchlistRelationType)}>
                  <option value="related_to">related_to</option>
                  <option value="underlying">underlying</option>
                  <option value="tracks">tracks</option>
                </select>
                <button type="button" className="btn-secondary" onClick={() => void handleCreateRelation()}>
                  建立关联
                </button>
              </div>
              <div className="space-y-2">
                {items.find((item) => item.id === draft.id)?.relations.map((relation) => (
                  <div key={relation.id} className="flex items-center justify-between rounded-lg border border-white/8 px-2 py-2 text-xs text-secondary">
                    <span>{relation.relationType} {'->'} {relation.targetSymbol}{relation.targetName ? ` (${relation.targetName})` : ''}</span>
                    <button type="button" className="text-red-300 hover:text-white" onClick={() => void handleDeleteRelation(relation.id)}>
                      删除
                    </button>
                  </div>
                ))}
                {!items.find((item) => item.id === draft.id)?.relations.length ? (
                  <p className="text-xs text-muted">当前暂无关联。</p>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      ) : null}
    </div>
  );
};

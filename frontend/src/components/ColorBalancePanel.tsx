/**
 * ColorBalancePanel
 * 타일 색상 균등 분배 테스트 도구
 * 5색상 × 3타일 = 15종 타일에서 색상 균등 선택 확인
 */

import { useState } from 'react';
import apiClient from '../api/client';

const COLOR_NAMES: Record<number, string> = {
  1: '색상1', 2: '색상2', 3: '색상3', 4: '색상4', 5: '색상5',
};

const COLOR_HEX: Record<number, string> = {
  1: '#ef4444', 2: '#3b82f6', 3: '#22c55e', 4: '#eab308', 5: '#a855f7',
};

interface TestResult {
  seed: number;
  tiles: string[];
  color_counts: Record<number, number>;
}

interface ColorTestResponse {
  tile_count: number;
  samples: number;
  color_buckets: Record<string, string[]>;
  results: TestResult[];
  color_totals: Record<number, number>;
  balance_score: number;
}

export function ColorBalancePanel() {
  const [tileCount, setTileCount] = useState(6);
  const [samples, setSamples] = useState(10);
  const [result, setResult] = useState<ColorTestResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const runTest = async () => {
    setIsLoading(true);
    try {
      const res = await apiClient.get(`/debug/color-balance-test?tile_count=${tileCount}&samples=${samples}`);
      setResult(res.data);
    } catch (err) {
      console.error('Color test failed:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const getTileColor = (tile: string): number => {
    const num = parseInt(tile.replace('t', ''));
    return Math.ceil(num / 3);
  };

  return (
    <div className="p-4 space-y-4">
      <h2 className="text-lg font-bold text-white">🎨 색상 균등 분배 테스트</h2>
      <p className="text-sm text-gray-400">
        15종 타일 (5색상 × 3타일)에서 지정 개수만큼 색상 균등하게 선택하는 결과를 확인합니다.
      </p>

      {/* 색상 버킷 표시 */}
      <div className="bg-gray-800 rounded-lg p-3">
        <h3 className="text-xs text-gray-400 mb-2">색상 버킷</h3>
        <div className="flex gap-3">
          {[1, 2, 3, 4, 5].map(c => (
            <div key={c} className="text-center">
              <div className="w-8 h-8 rounded mx-auto mb-1" style={{ backgroundColor: COLOR_HEX[c] }} />
              <div className="text-[10px] text-gray-400">{COLOR_NAMES[c]}</div>
              <div className="text-[10px] text-gray-500">t{(c-1)*3+1}~t{c*3}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 설정 */}
      <div className="flex items-center gap-4">
        <div>
          <label className="text-xs text-gray-400 block mb-1">타일 종류 수</label>
          <input type="range" min={3} max={15} value={tileCount}
            onChange={e => setTileCount(Number(e.target.value))}
            className="w-32"
          />
          <span className="text-white text-sm ml-2">{tileCount}종</span>
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">샘플 수</label>
          <input type="number" min={1} max={50} value={samples}
            onChange={e => setSamples(Number(e.target.value))}
            className="w-16 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white"
          />
        </div>
        <button onClick={runTest} disabled={isLoading}
          className="px-4 py-2 rounded text-sm bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-50 mt-4"
        >
          {isLoading ? '테스트 중...' : '테스트 실행'}
        </button>
      </div>

      {/* 결과 */}
      {result && (
        <div className="space-y-3">
          {/* 균형 점수 */}
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-300">균형 점수</span>
              <span className={`text-2xl font-bold ${
                result.balance_score >= 80 ? 'text-green-400' :
                result.balance_score >= 60 ? 'text-yellow-400' : 'text-red-400'
              }`}>
                {result.balance_score}%
              </span>
            </div>
            {/* 색상별 총 사용 횟수 막대 */}
            <div className="mt-3 space-y-1">
              {Object.entries(result.color_totals).map(([c, count]) => {
                const maxCount = Math.max(...Object.values(result.color_totals));
                const colorIdx = Number(c);
                return (
                  <div key={c} className="flex items-center gap-2">
                    <div className="w-4 h-4 rounded" style={{ backgroundColor: COLOR_HEX[colorIdx] }} />
                    <div className="w-8 text-[10px] text-gray-400">{COLOR_NAMES[colorIdx]}</div>
                    <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{
                        width: `${(count / maxCount) * 100}%`,
                        backgroundColor: COLOR_HEX[colorIdx],
                      }} />
                    </div>
                    <span className="text-xs text-gray-300 w-6 text-right">{count}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 개별 샘플 */}
          <div className="bg-gray-800 rounded-lg p-3">
            <h3 className="text-xs text-gray-400 mb-2">샘플 결과 ({result.samples}회)</h3>
            <div className="max-h-[400px] overflow-y-auto space-y-1">
              {result.results.map((r, i) => (
                <div key={i} className="flex items-center gap-2 py-1 border-b border-gray-700/50">
                  <span className="text-[10px] text-gray-500 w-6">#{i+1}</span>
                  <div className="flex gap-0.5">
                    {r.tiles.map((tile, j) => {
                      const colorIdx = getTileColor(tile);
                      return (
                        <div key={j}
                          className="w-6 h-6 rounded text-[8px] text-white flex items-center justify-center font-mono"
                          style={{ backgroundColor: COLOR_HEX[colorIdx] }}
                          title={`${tile} (${COLOR_NAMES[colorIdx]})`}
                        >
                          {tile.replace('t', '')}
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex gap-1 ml-2">
                    {Object.entries(r.color_counts).map(([c, cnt]) => (
                      cnt > 0 && (
                        <span key={c} className="text-[9px] px-1 rounded" style={{
                          backgroundColor: COLOR_HEX[Number(c)] + '30',
                          color: COLOR_HEX[Number(c)],
                        }}>
                          {cnt}
                        </span>
                      )
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

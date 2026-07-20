/**
 * 원격 연산(Cloud Run 등) 토글 — 무거운 컴퓨트(생성/RL검증/봇시뮬)만 원격 오프로드.
 * localStorage 'remote_compute_url' 설정 시 활성. 비우면 로컬(기본). 저장/조회는 항상 로컬.
 */
import { useState, useEffect } from 'react';
import axios from 'axios';
import { REMOTE_COMPUTE_KEY, getRemoteComputeUrl } from '../api/client';

export function RemoteComputeToggle() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState(getRemoteComputeUrl());
  const [active, setActive] = useState(!!getRemoteComputeUrl());
  const [testing, setTesting] = useState(false);
  const [status, setStatus] = useState<'idle' | 'ok' | 'fail'>('idle');

  useEffect(() => { setActive(!!getRemoteComputeUrl()); }, [open]);

  const test = async (u: string) => {
    setTesting(true); setStatus('idle');
    try {
      await axios.get(`${u.replace(/\/$/, '')}/docs`, { timeout: 8000 });
      setStatus('ok'); return true;
    } catch { setStatus('fail'); return false; }
    finally { setTesting(false); }
  };

  const connect = async () => {
    const u = url.trim().replace(/\/$/, '');
    if (!u) { disconnect(); return; }
    const ok = await test(u);
    if (ok) { localStorage.setItem(REMOTE_COMPUTE_KEY, u); setActive(true); }
    // 실패해도 저장은 안 함 → 로컬 유지(폴백)
  };
  const disconnect = () => { localStorage.removeItem(REMOTE_COMPUTE_KEY); setActive(false); setStatus('idle'); };

  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)}
        className={`px-3 py-2 text-sm font-medium rounded-md transition-colors ${active ? 'bg-emerald-700 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
        title="무거운 연산(생성/검증) 원격 오프로드 토글">
        {active ? '☁️ 원격 연산 ON' : '💻 로컬 연산'}
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-96 bg-gray-800 border border-gray-600 rounded-lg p-3 shadow-xl z-50 space-y-2">
          <div className="text-xs text-gray-300 font-medium">☁️ 원격 연산 (생성·RL검증·봇시뮬만)</div>
          <div className="text-[11px] text-gray-500 leading-relaxed">
            Cloud Run 등 원격 백엔드 URL 입력 → 무거운 연산만 그쪽에서. <b className="text-gray-300">저장/조회(템플릿·배치)는 항상 로컬</b>.
            비우거나 "로컬로" 누르면 즉시 기존 로컬 검증만.
          </div>
          <input value={url} onChange={e => setUrl(e.target.value)}
            placeholder="https://xxx.run.app"
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white" />
          <div className="flex items-center gap-2">
            <button onClick={connect} disabled={testing}
              className="px-3 py-1.5 rounded text-xs bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-50">
              {testing ? '연결테스트…' : '연결(테스트 후 저장)'}
            </button>
            <button onClick={disconnect}
              className="px-3 py-1.5 rounded text-xs bg-gray-600 hover:bg-gray-500 text-white">💻 로컬로</button>
            {status === 'ok' && <span className="text-[11px] text-emerald-400">✓ 연결됨</span>}
            {status === 'fail' && <span className="text-[11px] text-red-400">✗ 실패 → 로컬 유지</span>}
          </div>
          <div className="text-[10px] text-gray-500">현재: <b className={active ? 'text-emerald-400' : 'text-gray-400'}>{active ? getRemoteComputeUrl() : '로컬'}</b> · 계정 바꾸려면 새 URL로 재연결.</div>
        </div>
      )}
    </div>
  );
}

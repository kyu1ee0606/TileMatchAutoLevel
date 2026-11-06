/**
 * DDA 시드만 내보내기 — 화면 쪽 순수 판정(리뷰 반영 v2). React 의존 없음.
 *
 * - previewIdentity: 미리보기를 묶는 대상·옵션 식별값(배치 id/버전·범위·무한 모드·relabel·프리픽스·대상 목록).
 *   값이 바뀌면 미리보기·확인 체크를 버리고 전송을 막는다. 같은 selection 을 서버에도 보내 미리보기 때 값과 비교한다.
 * - chunkAbortReason: 청크 전송 직전 중단 사유. 미동기 편집 수는 **클라이언트가 세는 값**이라 서버가 독립적으로
 *   보장하지 못한다(서버 쪽 방어는 배치 파일 sha/version 재확인) — 그래서 청크마다 다시 읽어 양수면 즉시 멈춘다.
 */
export type SeedOnlySelection = Record<string, string | number | boolean | null>;

export function targetsKey(targets: Array<{ target_id: string; source_level: number }>): string {
  return targets.map(t => `${t.target_id}:${t.source_level}`).join(',');
}

export function previewIdentity(selection: SeedOnlySelection, targets?: Array<{ target_id: string; source_level: number }>): string {
  const keys = Object.keys(selection).sort();
  const sel = keys.map(k => [k, selection[k]]);
  return JSON.stringify({ sel, targets: targets ? targetsKey(targets) : null });
}

/** 청크 응답 뒤 다음 청크를 보내지 말아야 하는가(첫 실패 중단 원칙). */
export const STOP_REASONS = ['payload_invalid', 'interrupted_uncertain', 'stopped_after_failure'];
export function shouldStopAfterChunk(results: Array<{ status?: string; reason?: string }>): boolean {
  return results.some(x => x.status === 'failed' || STOP_REASONS.includes(x.reason ?? ''));
}

export function chunkAbortReason(s: {
  dirty: number;
  selectionNow: SeedOnlySelection;
  selectionAtPreview: SeedOnlySelection;
  tabVersionNow: number | undefined;
  tabVersionAtPreview: number;
}): string | null {
  if (s.dirty > 0) return `탭에 저장되지 않은 편집 ${s.dirty}개 — 전송 중단`;
  if (previewIdentity(s.selectionNow) !== previewIdentity(s.selectionAtPreview)) return '대상/옵션이 미리보기 후 바뀜 — 전송 중단';
  if (s.tabVersionNow !== s.tabVersionAtPreview) return `탭 배치 버전이 바뀜(v${s.tabVersionAtPreview} → v${s.tabVersionNow ?? '?'}) — 전송 중단`;
  return null;
}

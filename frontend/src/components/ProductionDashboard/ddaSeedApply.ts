/**
 * 'DDA 시드 갱신' 적용 단계 (문서 47) — 저장소 접근을 주입받는 순수 로직(검증용 분리).
 * update 계획만 저장. 미저장 편집 레벨/검사 후 바뀐 레벨(경합)은 건너뛰고, 실패는 레벨별로 모은다.
 */
import type { ProductionLevel } from '../../types/production';
import type { DdaLevelPlan, DdaSeedField } from '../../api/ddaSeeds';

const FIELDS: DdaSeedField[] = ['ddaEasySeeds', 'ddaHardSeeds'];

export interface DdaApplyResult {
  saved: number[];
  raced: number[];
  skippedDirty: number[];
  failed: Array<{ level: number; message: string }>;
}

export async function applyDdaPlans(
  plans: DdaLevelPlan[],
  /** 사전검사 시점 level_json 직렬화 (update 레벨만) */
  snapshot: Map<number, string>,
  unsavedLevelNumber: number | null,
  getLevel: (levelNumber: number) => Promise<ProductionLevel | null>,
  saveLevel: (level: ProductionLevel) => Promise<void>,
): Promise<DdaApplyResult> {
  const out: DdaApplyResult = { saved: [], raced: [], skippedDirty: [], failed: [] };
  for (const plan of plans.filter(r => r.action === 'update')) {
    if (unsavedLevelNumber !== null && plan.level === unsavedLevelNumber) {
      out.skippedDirty.push(plan.level);
      continue;
    }
    try {
      const cur = await getLevel(plan.level);
      if (!cur || JSON.stringify(cur.level_json) !== snapshot.get(plan.level)) {
        out.raced.push(plan.level);            // 검사 후 편집됨 → 덮어쓰지 않음
        continue;
      }
      const next = { ...cur.level_json };
      for (const f of FIELDS) {
        const fp = plan.fields?.[f];
        if (fp && (fp.state === 'missing' || fp.state === 'invalid') && fp.after) next[f] = fp.after;
      }
      await saveLevel({ ...cur, level_json: next });
      out.saved.push(plan.level);
    } catch (e) {
      out.failed.push({ level: plan.level, message: (e as Error).message });
    }
  }
  return out;
}

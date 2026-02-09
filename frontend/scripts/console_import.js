// 이 스크립트를 브라우저 콘솔에 붙여넣으세요 (F12 → Console)
// http://localhost:5173 에서 실행해야 합니다

(async function() {
  const levels = PASTE_LEVELS_HERE;
  
  const LOCAL_LEVELS_KEY = 'tilematch_local_levels';
  const now = new Date().toISOString();
  
  let existing = [];
  try {
    const stored = localStorage.getItem(LOCAL_LEVELS_KEY);
    if (stored) existing = JSON.parse(stored);
  } catch (e) {}
  
  const newLevels = levels.map(l => ({
    id: l.id,
    name: l.name,
    description: '패턴 믹싱 테스트',
    tags: l.tags || ['pattern_mix'],
    source: 'api_test',
    level_data: l.level_data,
    created_at: l.created_at || now,
    saved_at: now,
    difficulty: l.difficulty,
    grade: l.grade,
    validation_status: 'not_tested'
  }));
  
  const existingIds = new Set(existing.map(l => l.id));
  const toAdd = newLevels.filter(l => !existingIds.has(l.id));
  const merged = [...existing, ...toAdd];
  
  localStorage.setItem(LOCAL_LEVELS_KEY, JSON.stringify(merged));
  
  console.log(`✅ ${toAdd.length}개 레벨 추가됨! (전체: ${merged.length}개)`);
  console.log('🔄 페이지를 새로고침하세요!');
})();

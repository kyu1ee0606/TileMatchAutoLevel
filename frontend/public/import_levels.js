// Auto-import script for pattern mix levels
(async function() {
  try {
    // Fetch the levels data
    const response = await fetch('/test_levels.json');
    const levels = await response.json();
    
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
    
    alert('✅ ' + toAdd.length + '개 레벨 추가됨!\n페이지를 새로고침하세요.');
    location.reload();
  } catch (e) {
    alert('❌ 오류: ' + e.message);
  }
})();

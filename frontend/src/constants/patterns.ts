/**
 * 레벨 모양 패턴 상수 정의
 * generator.py의 _generate_aesthetic_positions에서 정의된 64개 패턴 매핑
 */

export interface Pattern {
  index: number;
  name: string;
  nameKo: string;
  icon: string;
}

export interface PatternCategory {
  id: string;
  name: string;
  nameKo: string;
  patterns: Pattern[];
}

export const PATTERN_CATEGORIES: PatternCategory[] = [
  {
    id: 'basic',
    name: 'Basic Shapes',
    nameKo: '기본 도형',
    patterns: [
      { index: 0, name: 'Rectangle', nameKo: '사각형', icon: '▢' },
      { index: 1, name: 'Diamond', nameKo: '다이아몬드', icon: '◇' },
      { index: 2, name: 'Oval', nameKo: '타원', icon: '⬭' },
      { index: 3, name: 'Cross', nameKo: '십자가', icon: '✚' },
      { index: 4, name: 'Donut', nameKo: '도넛', icon: '◎' },
      { index: 5, name: 'Concentric Diamond', nameKo: '동심 다이아몬드', icon: '◈' },
      { index: 6, name: 'Corner Anchored', nameKo: '코너 앵커', icon: '⌗' },
      { index: 7, name: 'Hexagonal', nameKo: '육각형', icon: '⬡' },
      { index: 8, name: 'Heart', nameKo: '하트', icon: '❤️' },
      { index: 9, name: 'T-Shape', nameKo: 'T자', icon: '⊤' },
    ],
  },
  {
    id: 'arrow',
    name: 'Arrows',
    nameKo: '화살표',
    patterns: [
      { index: 10, name: 'Arrow Up', nameKo: '화살표 ↑', icon: '⬆️' },
      { index: 11, name: 'Arrow Down', nameKo: '화살표 ↓', icon: '⬇️' },
      { index: 12, name: 'Arrow Left', nameKo: '화살표 ←', icon: '⬅️' },
      { index: 13, name: 'Arrow Right', nameKo: '화살표 →', icon: '➡️' },
      { index: 14, name: 'Chevron', nameKo: '쉐브론', icon: '⋀' },
    ],
  },
  {
    id: 'celestial',
    name: 'Stars & Celestial',
    nameKo: '별/천체',
    patterns: [
      { index: 15, name: 'Star 5-pointed', nameKo: '별 5각', icon: '⭐' },
      { index: 16, name: 'Star 6-pointed', nameKo: '별 6각', icon: '✡️' },
      { index: 17, name: 'Crescent Moon', nameKo: '초승달', icon: '🌙' },
      { index: 18, name: 'Sun Burst', nameKo: '태양', icon: '☀️' },
      { index: 19, name: 'Spiral', nameKo: '나선', icon: '🌀' },
    ],
  },
  {
    id: 'letters',
    name: 'Letters',
    nameKo: '문자',
    patterns: [
      { index: 20, name: 'Letter H', nameKo: 'H', icon: 'H' },
      { index: 21, name: 'Letter I', nameKo: 'I', icon: 'I' },
      { index: 22, name: 'Letter L', nameKo: 'L', icon: 'L' },
      { index: 23, name: 'Letter U', nameKo: 'U', icon: 'U' },
      { index: 24, name: 'Letter X', nameKo: 'X', icon: 'X' },
      { index: 25, name: 'Letter Y', nameKo: 'Y', icon: 'Y' },
      { index: 26, name: 'Letter Z', nameKo: 'Z', icon: 'Z' },
      { index: 27, name: 'Letter S', nameKo: 'S', icon: 'S' },
      { index: 28, name: 'Letter O', nameKo: 'O', icon: 'O' },
      { index: 29, name: 'Letter C', nameKo: 'C', icon: 'C' },
    ],
  },
  {
    id: 'geometric',
    name: 'Geometric',
    nameKo: '기하학',
    patterns: [
      { index: 30, name: 'Triangle Up', nameKo: '삼각형 ▲', icon: '▲' },
      { index: 31, name: 'Triangle Down', nameKo: '삼각형 ▼', icon: '▼' },
      { index: 32, name: 'Hourglass', nameKo: '모래시계', icon: '⧗' },
      { index: 33, name: 'Bowtie', nameKo: '나비넥타이', icon: '⋈' },
      { index: 34, name: 'Stairs Ascending', nameKo: '계단 ↗', icon: '📶' },
      { index: 35, name: 'Stairs Descending', nameKo: '계단 ↘', icon: '📉' },
      { index: 36, name: 'Pyramid', nameKo: '피라미드', icon: '△' },
      { index: 37, name: 'Inverted Pyramid', nameKo: '역피라미드', icon: '▽' },
      { index: 38, name: 'Zigzag', nameKo: '지그재그', icon: '⚡' },
      { index: 39, name: 'Wave', nameKo: '물결', icon: '〰️' },
    ],
  },
  {
    id: 'frame',
    name: 'Frames',
    nameKo: '프레임',
    patterns: [
      { index: 40, name: 'Frame Border', nameKo: '프레임 테두리', icon: '⬜' },
      { index: 41, name: 'Double Frame', nameKo: '이중 프레임', icon: '⧈' },
      { index: 42, name: 'Corner Triangles', nameKo: '코너 삼각형', icon: '◢' },
      { index: 43, name: 'Center Hollow', nameKo: '중앙 비움', icon: '⬚' },
      { index: 44, name: 'Window Panes', nameKo: '창문', icon: '⊞' },
    ],
  },
  {
    id: 'artistic',
    name: 'Artistic',
    nameKo: '예술',
    patterns: [
      { index: 45, name: 'Butterfly', nameKo: '나비', icon: '🦋' },
      { index: 46, name: 'Flower', nameKo: '꽃', icon: '🌸' },
      { index: 47, name: 'Scattered Islands', nameKo: '산재 섬', icon: '🏝️' },
      { index: 48, name: 'Diagonal Stripes', nameKo: '대각선 줄무늬', icon: '╱' },
      { index: 49, name: 'Honeycomb', nameKo: '벌집', icon: '🍯' },
    ],
  },
  {
    id: 'islands',
    name: 'Islands & Bridges',
    nameKo: '섬/브릿지',
    patterns: [
      { index: 50, name: 'Horizontal Bridge', nameKo: '가로 브릿지', icon: '═' },
      { index: 51, name: 'Vertical Bridge', nameKo: '세로 브릿지', icon: '║' },
      { index: 52, name: 'Three Islands Triangle', nameKo: '삼각 섬', icon: '∴' },
      { index: 53, name: 'Four Islands Grid', nameKo: '사각 섬', icon: '⊕' },
      { index: 54, name: 'Archipelago', nameKo: '군도', icon: '🗾' },
      { index: 55, name: 'Central Hub', nameKo: '중앙 허브', icon: '⊛' },
    ],
  },
  {
    id: 'gboost',
    name: 'GBoost Patterns',
    nameKo: 'GBoost',
    patterns: [
      { index: 56, name: 'Corner Blocks', nameKo: '코너 블록', icon: '⌐' },
      { index: 57, name: 'Octagon Ring', nameKo: '팔각 링', icon: '⯃' },
      { index: 58, name: 'Diagonal Staircase', nameKo: '대각 계단', icon: '⤡' },
      { index: 59, name: 'Symmetric Wings', nameKo: '대칭 날개', icon: '🪽' },
      { index: 60, name: 'Scattered Clusters', nameKo: '산재 클러스터', icon: '⁘' },
      { index: 61, name: 'Cross Bridge', nameKo: '십자 브릿지', icon: '╋' },
      { index: 62, name: 'Triple Bar', nameKo: '삼중 바', icon: '☰' },
      { index: 63, name: 'Frame with Center', nameKo: '센터 프레임', icon: '⊡' },
    ],
  },
  {
    id: 'layered',
    name: 'Layered Patterns',
    nameKo: '레이어드',
    patterns: [
      { index: 64, name: 'Nested Frames', nameKo: '중첩 프레임', icon: '🔳' },
    ],
  },
];

// 전체 패턴 플랫 리스트
export const ALL_PATTERNS: Pattern[] = PATTERN_CATEGORIES.flatMap(cat => cat.patterns);

// 인덱스로 패턴 찾기
export const getPatternByIndex = (index: number): Pattern | undefined => {
  return ALL_PATTERNS.find(p => p.index === index);
};

// 카테고리별 추천 패턴 (보스/특수 레벨용)
export const BOSS_PATTERNS = [8, 15, 16, 45, 46, 17, 18]; // 하트, 별, 나비, 꽃 등
export const SPECIAL_PATTERNS = [3, 4, 20, 23, 24, 30, 33]; // 십자가, 도넛, 문자, 삼각형 등
export const EASY_PATTERNS = [0, 1, 2, 3, 4, 8]; // 단순 도형

// 인기 패턴 (빠른 선택용)
export const POPULAR_PATTERNS = [
  { index: 8, name: '하트', icon: '❤️' },
  { index: 15, name: '별', icon: '⭐' },
  { index: 1, name: '다이아몬드', icon: '◇' },
  { index: 45, name: '나비', icon: '🦋' },
  { index: 46, name: '꽃', icon: '🌸' },
  { index: 3, name: '십자가', icon: '✚' },
];

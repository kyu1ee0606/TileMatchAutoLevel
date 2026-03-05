import { useState, useCallback } from 'react';
import clsx from 'clsx';
import {
  PATTERN_CATEGORIES,
  POPULAR_PATTERNS,
  getPatternByIndex,
} from '../../constants/patterns';

interface PatternSelectorProps {
  value: number | undefined;
  onChange: (patternIndex: number | undefined) => void;
  disabled?: boolean;
  showPopular?: boolean;
  className?: string;
}

export function PatternSelector({
  value,
  onChange,
  disabled = false,
  showPopular = true,
  className,
}: PatternSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string>('basic');

  const selectedPattern = value !== undefined ? getPatternByIndex(value) : undefined;

  const handleSelect = useCallback((index: number | undefined) => {
    onChange(index);
    setIsOpen(false);
  }, [onChange]);

  const currentCategory = PATTERN_CATEGORIES.find(c => c.id === selectedCategory);

  return (
    <div className={clsx('relative', className)}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={clsx(
          'flex items-center gap-2 px-3 py-2 rounded-lg border transition-colors w-full',
          'bg-gray-800 border-gray-600 hover:border-gray-500',
          disabled && 'opacity-50 cursor-not-allowed',
          isOpen && 'border-blue-500'
        )}
      >
        {selectedPattern ? (
          <>
            <span className="text-xl">{selectedPattern.icon}</span>
            <span className="text-sm text-gray-200">{selectedPattern.nameKo}</span>
          </>
        ) : (
          <>
            <span className="text-xl text-gray-400">🎲</span>
            <span className="text-sm text-gray-400">자동 선택</span>
          </>
        )}
        <svg
          className={clsx('w-4 h-4 ml-auto text-gray-400 transition-transform', isOpen && 'rotate-180')}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown Panel */}
      {isOpen && (
        <div className="absolute z-50 mt-1 w-80 bg-gray-800 border border-gray-600 rounded-lg shadow-xl">
          {/* Popular Patterns */}
          {showPopular && (
            <div className="p-2 border-b border-gray-700">
              <div className="text-xs text-gray-400 mb-2">인기 패턴</div>
              <div className="flex flex-wrap gap-1">
                <button
                  onClick={() => handleSelect(undefined)}
                  className={clsx(
                    'px-2 py-1 rounded text-sm flex items-center gap-1 transition-colors',
                    value === undefined
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  )}
                >
                  <span>🎲</span>
                  <span>자동</span>
                </button>
                {POPULAR_PATTERNS.map(p => (
                  <button
                    key={p.index}
                    onClick={() => handleSelect(p.index)}
                    className={clsx(
                      'px-2 py-1 rounded text-sm flex items-center gap-1 transition-colors',
                      value === p.index
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    )}
                    title={p.name}
                  >
                    <span>{p.icon}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Category Tabs */}
          <div className="flex flex-wrap gap-1 p-2 border-b border-gray-700 bg-gray-750">
            {PATTERN_CATEGORIES.map(cat => (
              <button
                key={cat.id}
                onClick={() => setSelectedCategory(cat.id)}
                className={clsx(
                  'px-2 py-1 rounded text-xs transition-colors',
                  selectedCategory === cat.id
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                )}
              >
                {cat.nameKo}
              </button>
            ))}
          </div>

          {/* Pattern Grid */}
          {currentCategory && (
            <div className="p-2 max-h-48 overflow-y-auto">
              <div className="grid grid-cols-5 gap-1">
                {currentCategory.patterns.map(pattern => (
                  <button
                    key={pattern.index}
                    onClick={() => handleSelect(pattern.index)}
                    className={clsx(
                      'flex flex-col items-center justify-center p-2 rounded transition-colors',
                      value === pattern.index
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    )}
                    title={`${pattern.nameKo} (${pattern.index})`}
                  >
                    <span className="text-xl">{pattern.icon}</span>
                    <span className="text-[10px] mt-0.5 truncate w-full text-center">
                      {pattern.nameKo}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Clear Selection */}
          <div className="p-2 border-t border-gray-700 flex justify-end gap-2">
            <button
              onClick={() => handleSelect(undefined)}
              className="px-3 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600 transition-colors"
            >
              자동 선택으로
            </button>
            <button
              onClick={() => setIsOpen(false)}
              className="px-3 py-1 text-xs bg-gray-600 text-gray-200 rounded hover:bg-gray-500 transition-colors"
            >
              닫기
            </button>
          </div>
        </div>
      )}

      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setIsOpen(false)}
        />
      )}
    </div>
  );
}

// Compact inline version for tables/lists
export function PatternSelectorInline({
  value,
  onChange,
  disabled = false,
}: Omit<PatternSelectorProps, 'showPopular' | 'className'>) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedPattern = value !== undefined ? getPatternByIndex(value) : undefined;

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={clsx(
          'flex items-center gap-1 px-2 py-1 rounded text-sm transition-colors',
          'bg-gray-700 hover:bg-gray-600',
          disabled && 'opacity-50 cursor-not-allowed'
        )}
      >
        <span>{selectedPattern?.icon ?? '🎲'}</span>
        <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <>
          <div className="absolute z-50 mt-1 right-0 bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-2">
            <div className="grid grid-cols-6 gap-1 max-w-xs">
              <button
                onClick={() => { onChange(undefined); setIsOpen(false); }}
                className={clsx(
                  'p-1.5 rounded text-lg',
                  value === undefined ? 'bg-blue-600' : 'bg-gray-700 hover:bg-gray-600'
                )}
                title="자동 선택"
              >
                🎲
              </button>
              {POPULAR_PATTERNS.map(p => (
                <button
                  key={p.index}
                  onClick={() => { onChange(p.index); setIsOpen(false); }}
                  className={clsx(
                    'p-1.5 rounded text-lg',
                    value === p.index ? 'bg-blue-600' : 'bg-gray-700 hover:bg-gray-600'
                  )}
                  title={p.name}
                >
                  {p.icon}
                </button>
              ))}
            </div>
          </div>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
        </>
      )}
    </div>
  );
}

export default PatternSelector;

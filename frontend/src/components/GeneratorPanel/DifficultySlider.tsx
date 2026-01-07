import { getGradeColor, getGradeDescription } from '../../utils/helpers';
import type { DifficultyGrade } from '../../types';
import clsx from 'clsx';

interface DifficultySliderProps {
  value: number;
  onChange: (value: number) => void;
  className?: string;
}

function getGradeFromDifficulty(difficulty: number): DifficultyGrade {
  const score = difficulty * 100;
  if (score <= 20) return 'S';
  if (score <= 40) return 'A';
  if (score <= 60) return 'B';
  if (score <= 80) return 'C';
  return 'D';
}

export function DifficultySlider({ value, onChange, className }: DifficultySliderProps) {
  const grade = getGradeFromDifficulty(value);
  const gradeColor = getGradeColor(grade);
  const gradeDescription = getGradeDescription(grade);
  const percentage = Math.round(value * 100);

  return (
    <div className={clsx('', className)}>
      <div className="flex justify-between items-center mb-2">
        <label className="text-sm font-medium text-gray-300">목표 난이도</label>
        <div className="flex items-center gap-2">
          <span
            className="w-8 h-8 rounded-md flex items-center justify-center text-white font-bold text-sm"
            style={{ backgroundColor: gradeColor }}
          >
            {grade}
          </span>
          <span className="text-sm text-gray-400">{gradeDescription}</span>
        </div>
      </div>

      <div className="relative">
        {/* Grade boundary marks */}
        <div className="absolute inset-0 flex items-center pointer-events-none h-3">
          {[20, 40, 60, 80].map((boundary) => (
            <div
              key={boundary}
              className="absolute w-0.5 h-4 bg-gray-500/50 -top-0.5"
              style={{ left: `${boundary}%`, transform: 'translateX(-50%)' }}
            />
          ))}
        </div>
        <input
          type="range"
          min="0"
          max="100"
          value={percentage}
          onChange={(e) => onChange(parseInt(e.target.value) / 100)}
          className="w-full h-3 bg-gray-700 rounded-lg appearance-none cursor-pointer slider-thumb relative z-10"
          style={{
            background: `linear-gradient(to right, ${gradeColor} ${percentage}%, #374151 ${percentage}%)`,
          }}
        />
        <div className="flex justify-between text-xs mt-1">
          {(['S', 'A', 'B', 'C', 'D'] as const).map((g) => (
            <span
              key={g}
              className={clsx(
                'w-5 text-center font-medium transition-colors',
                grade === g ? 'text-white' : 'text-gray-500'
              )}
              style={grade === g ? { color: getGradeColor(g) } : {}}
            >
              {g}
            </span>
          ))}
        </div>
      </div>

      <div className="text-center mt-2">
        <span className="text-2xl font-bold" style={{ color: gradeColor }}>
          {percentage}%
        </span>
      </div>
    </div>
  );
}

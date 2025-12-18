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
        <input
          type="range"
          min="0"
          max="100"
          value={percentage}
          onChange={(e) => onChange(parseInt(e.target.value) / 100)}
          className="w-full h-3 bg-gray-700 rounded-lg appearance-none cursor-pointer slider-thumb"
          style={{
            background: `linear-gradient(to right, ${gradeColor} ${percentage}%, #374151 ${percentage}%)`,
          }}
        />
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>S</span>
          <span>A</span>
          <span>B</span>
          <span>C</span>
          <span>D</span>
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

import { getGradeColor, getGradeDescription } from '../../utils/helpers';
import type { DifficultyGrade } from '../../types';
import clsx from 'clsx';

interface ScoreDisplayProps {
  score: number;
  grade: DifficultyGrade;
  className?: string;
}

export function ScoreDisplay({ score, grade, className }: ScoreDisplayProps) {
  const gradeColor = getGradeColor(grade);
  const gradeDescription = getGradeDescription(grade);
  const percentage = score;

  return (
    <div className={clsx('flex flex-col gap-4', className)}>
      {/* Score Bar */}
      <div>
        <div className="flex justify-between mb-1">
          <span className="text-sm font-medium text-gray-300">난이도 점수</span>
          <span className="text-sm font-bold" style={{ color: gradeColor }}>
            {score.toFixed(1)} / 100
          </span>
        </div>
        <div className="w-full bg-gray-700 rounded-full h-4 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${Math.min(100, percentage)}%`,
              backgroundColor: gradeColor,
            }}
          />
        </div>
      </div>

      {/* Grade Display */}
      <div className="flex items-center gap-4">
        <div
          className="w-16 h-16 rounded-xl flex items-center justify-center text-white text-3xl font-bold shadow-lg"
          style={{ backgroundColor: gradeColor }}
        >
          {grade}
        </div>
        <div>
          <div className="text-lg font-bold text-gray-100">등급: {grade}</div>
          <div className="text-sm text-gray-400">{gradeDescription}</div>
        </div>
      </div>
    </div>
  );
}

/**
 * LevelDistributionChart
 * 프로덕션 레벨 1~1500의 분포를 시각화하는 차트 컴포넌트
 */

import { useMemo, useState, useCallback } from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  Tooltip,
  ResponsiveContainer,
  Brush,
  CartesianGrid,
  Legend,
  ReferenceLine,
} from 'recharts';
import type { ProductionLevel } from '../../types/production';
import type { DifficultyGrade } from '../../types';

type YAxisMode = 'difficulty' | 'casual_rate' | 'average_rate' | 'expert_rate' | 'match_score';
type VerificationStatus = 'passed' | 'failed' | 'unverified' | 'missing';

interface ChartDataPoint {
  x: number;  // level_number
  y: number;  // Y axis value
  status: VerificationStatus;
  grade: DifficultyGrade;
  level: ProductionLevel | null;
  matchScore?: number;
}

interface LevelDistributionChartProps {
  levels: ProductionLevel[];
  totalLevels?: number;  // 1500
  onLevelClick?: (level: ProductionLevel) => void;
}

interface StatusGroupedData {
  passed: ChartDataPoint[];
  failed: ChartDataPoint[];
  unverified: ChartDataPoint[];
  missing: ChartDataPoint[];
}

interface GradeGroupedData {
  S: ChartDataPoint[];
  A: ChartDataPoint[];
  B: ChartDataPoint[];
  C: ChartDataPoint[];
  D: ChartDataPoint[];
  missing: ChartDataPoint[];
}

// Status colors matching TODO spec
const STATUS_COLORS: Record<VerificationStatus, string> = {
  passed: '#22c55e',     // green-500
  failed: '#ef4444',     // red-500
  unverified: '#eab308', // yellow-500
  missing: '#6b7280',    // gray-500
};

const GRADE_COLORS: Record<DifficultyGrade, string> = {
  S: '#22c55e',
  A: '#3b82f6',
  B: '#eab308',
  C: '#f97316',
  D: '#ef4444',
};

const Y_AXIS_OPTIONS: { value: YAxisMode; label: string }[] = [
  { value: 'difficulty', label: '목표 난이도' },
  { value: 'casual_rate', label: 'Casual 클리어율' },
  { value: 'average_rate', label: 'Average 클리어율' },
  { value: 'expert_rate', label: 'Expert 클리어율' },
  { value: 'match_score', label: '매치 점수' },
];

export function LevelDistributionChart({
  levels,
  totalLevels = 1500,
  onLevelClick,
}: LevelDistributionChartProps) {
  const [yAxisMode, setYAxisMode] = useState<YAxisMode>('difficulty');
  const [colorMode, setColorMode] = useState<'status' | 'grade'>('status');

  // Transform levels to chart data
  const { chartData, stats } = useMemo(() => {
    const levelMap = new Map<number, ProductionLevel>();
    levels.forEach(l => levelMap.set(l.meta.level_number, l));

    const data: ChartDataPoint[] = [];
    let passedCount = 0;
    let failedCount = 0;
    let unverifiedCount = 0;
    let missingCount = 0;

    for (let i = 1; i <= totalLevels; i++) {
      const level = levelMap.get(i) || null;

      if (!level) {
        // Missing level
        missingCount++;
        data.push({
          x: i,
          y: 0,
          status: 'missing',
          grade: 'B',
          level: null,
        });
        continue;
      }

      // Determine verification status
      let status: VerificationStatus;
      if (level.meta.verified) {
        status = level.meta.verification_passed ? 'passed' : 'failed';
        if (status === 'passed') passedCount++;
        else failedCount++;
      } else {
        status = 'unverified';
        unverifiedCount++;
      }

      // Get Y value based on mode
      let yValue: number;
      switch (yAxisMode) {
        case 'difficulty':
          yValue = level.meta.target_difficulty * 100;
          break;
        case 'casual_rate':
          yValue = (level.meta.bot_clear_rates?.casual ?? 0) * 100;
          break;
        case 'average_rate':
          yValue = (level.meta.bot_clear_rates?.average ?? 0) * 100;
          break;
        case 'expert_rate':
          yValue = (level.meta.bot_clear_rates?.expert ?? 0) * 100;
          break;
        case 'match_score':
          yValue = level.meta.match_score ?? 0;
          break;
        default:
          yValue = level.meta.target_difficulty * 100;
      }

      data.push({
        x: i,
        y: yValue,
        status,
        grade: level.meta.grade,
        level,
        matchScore: level.meta.match_score,
      });
    }

    return {
      chartData: data,
      stats: {
        total: levels.length,
        passed: passedCount,
        failed: failedCount,
        unverified: unverifiedCount,
        missing: missingCount,
      },
    };
  }, [levels, totalLevels, yAxisMode]);

  // Group data by status for scatter series
  const statusGroupedData: StatusGroupedData = useMemo(() => ({
    passed: chartData.filter(d => d.status === 'passed'),
    failed: chartData.filter(d => d.status === 'failed'),
    unverified: chartData.filter(d => d.status === 'unverified'),
    missing: chartData.filter(d => d.status === 'missing'),
  }), [chartData]);

  // Group data by grade for scatter series
  const gradeGroupedData: GradeGroupedData = useMemo(() => ({
    S: chartData.filter(d => d.grade === 'S' && d.status !== 'missing'),
    A: chartData.filter(d => d.grade === 'A' && d.status !== 'missing'),
    B: chartData.filter(d => d.grade === 'B' && d.status !== 'missing'),
    C: chartData.filter(d => d.grade === 'C' && d.status !== 'missing'),
    D: chartData.filter(d => d.grade === 'D' && d.status !== 'missing'),
    missing: chartData.filter(d => d.status === 'missing'),
  }), [chartData]);

  // Click handler
  const handleClick = useCallback((data: ChartDataPoint) => {
    if (data.level && onLevelClick) {
      onLevelClick(data.level);
    }
  }, [onLevelClick]);

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: { payload: ChartDataPoint }[] }) => {
    if (!active || !payload || !payload.length) return null;

    const data = payload[0].payload;
    if (!data.level) {
      return (
        <div className="bg-gray-900 border border-gray-700 rounded px-3 py-2 shadow-lg">
          <p className="text-gray-400">레벨 {data.x}: 미생성</p>
        </div>
      );
    }

    const { meta } = data.level;
    return (
      <div className="bg-gray-900 border border-gray-700 rounded px-3 py-2 shadow-lg text-sm">
        <p className="font-bold text-white mb-1">레벨 {meta.level_number}</p>
        <div className="space-y-0.5 text-gray-300">
          <p>등급: <span className={getGradeTextColor(meta.grade)}>{meta.grade}</span></p>
          <p>목표 난이도: {(meta.target_difficulty * 100).toFixed(0)}%</p>
          {meta.match_score !== undefined && (
            <p>매치 점수: <span className={meta.match_score >= 70 ? 'text-green-400' : 'text-red-400'}>
              {meta.match_score.toFixed(1)}
            </span></p>
          )}
          {meta.bot_clear_rates && (
            <>
              <p>Casual: {(meta.bot_clear_rates.casual * 100).toFixed(0)}%</p>
              <p>Average: {(meta.bot_clear_rates.average * 100).toFixed(0)}%</p>
              <p>Expert: {(meta.bot_clear_rates.expert * 100).toFixed(0)}%</p>
            </>
          )}
          <p className="mt-1 pt-1 border-t border-gray-700">
            검증: {meta.verified
              ? (meta.verification_passed ? '✅ 통과' : '❌ 실패')
              : '⏳ 미검증'}
          </p>
        </div>
      </div>
    );
  };

  // Y axis config
  const yAxisConfig = useMemo(() => {
    switch (yAxisMode) {
      case 'difficulty':
        return { domain: [0, 100], label: '목표 난이도 (%)' };
      case 'match_score':
        return { domain: [0, 100], label: '매치 점수' };
      default:
        return { domain: [0, 100], label: '클리어율 (%)' };
    }
  }, [yAxisMode]);

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-white">레벨 분포도</h3>

        {/* Controls */}
        <div className="flex items-center gap-4">
          {/* Y Axis selector */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">Y축:</span>
            <select
              value={yAxisMode}
              onChange={(e) => setYAxisMode(e.target.value as YAxisMode)}
              className="bg-gray-700 text-white text-sm rounded px-2 py-1 border border-gray-600"
            >
              {Y_AXIS_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Color mode selector */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">색상:</span>
            <select
              value={colorMode}
              onChange={(e) => setColorMode(e.target.value as 'status' | 'grade')}
              className="bg-gray-700 text-white text-sm rounded px-2 py-1 border border-gray-600"
            >
              <option value="status">검증 상태</option>
              <option value="grade">난이도 등급</option>
            </select>
          </div>
        </div>
      </div>

      {/* Stats Summary */}
      <div className="flex gap-4 mb-4 text-sm">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: STATUS_COLORS.passed }} />
          <span className="text-gray-300">통과: {stats.passed}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: STATUS_COLORS.failed }} />
          <span className="text-gray-300">실패: {stats.failed}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: STATUS_COLORS.unverified }} />
          <span className="text-gray-300">미검증: {stats.unverified}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: STATUS_COLORS.missing }} />
          <span className="text-gray-300">미생성: {stats.missing}</span>
        </div>
        <div className="ml-auto text-gray-400">
          총 {stats.total}개 레벨 / {totalLevels}
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 10, right: 30, bottom: 10, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            type="number"
            dataKey="x"
            domain={[1, totalLevels]}
            name="레벨"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            tickLine={{ stroke: '#4b5563' }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={yAxisConfig.domain}
            name={yAxisConfig.label}
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            tickLine={{ stroke: '#4b5563' }}
            axisLine={{ stroke: '#4b5563' }}
            label={{
              value: yAxisConfig.label,
              angle: -90,
              position: 'insideLeft',
              fill: '#9ca3af',
              fontSize: 11,
            }}
          />
          <ZAxis range={[20, 20]} />
          <Tooltip content={<CustomTooltip />} />

          {/* Reference line for match score threshold */}
          {yAxisMode === 'match_score' && (
            <ReferenceLine y={70} stroke="#22c55e" strokeDasharray="5 5" label={{ value: '70점 기준', fill: '#22c55e', fontSize: 10 }} />
          )}

          {/* Scatter series by color mode */}
          {colorMode === 'status' ? (
            <>
              <Scatter
                name="검증 통과"
                data={statusGroupedData.passed}
                fill={STATUS_COLORS.passed}
                onClick={(data) => handleClick(data as unknown as ChartDataPoint)}
                cursor="pointer"
              />
              <Scatter
                name="검증 실패"
                data={statusGroupedData.failed}
                fill={STATUS_COLORS.failed}
                onClick={(data) => handleClick(data as unknown as ChartDataPoint)}
                cursor="pointer"
              />
              <Scatter
                name="미검증"
                data={statusGroupedData.unverified}
                fill={STATUS_COLORS.unverified}
                onClick={(data) => handleClick(data as unknown as ChartDataPoint)}
                cursor="pointer"
              />
              <Scatter
                name="미생성"
                data={statusGroupedData.missing}
                fill={STATUS_COLORS.missing}
              />
            </>
          ) : (
            <>
              <Scatter name="S등급" data={gradeGroupedData.S} fill={GRADE_COLORS.S} onClick={(data) => handleClick(data as unknown as ChartDataPoint)} cursor="pointer" />
              <Scatter name="A등급" data={gradeGroupedData.A} fill={GRADE_COLORS.A} onClick={(data) => handleClick(data as unknown as ChartDataPoint)} cursor="pointer" />
              <Scatter name="B등급" data={gradeGroupedData.B} fill={GRADE_COLORS.B} onClick={(data) => handleClick(data as unknown as ChartDataPoint)} cursor="pointer" />
              <Scatter name="C등급" data={gradeGroupedData.C} fill={GRADE_COLORS.C} onClick={(data) => handleClick(data as unknown as ChartDataPoint)} cursor="pointer" />
              <Scatter name="D등급" data={gradeGroupedData.D} fill={GRADE_COLORS.D} onClick={(data) => handleClick(data as unknown as ChartDataPoint)} cursor="pointer" />
              <Scatter name="미생성" data={gradeGroupedData.missing} fill={STATUS_COLORS.missing} />
            </>
          )}

          <Legend
            wrapperStyle={{ paddingTop: 10 }}
            formatter={(value) => <span style={{ color: '#9ca3af', fontSize: 11 }}>{value}</span>}
          />

          {/* Brush for range selection */}
          <Brush
            dataKey="x"
            height={25}
            stroke="#4b5563"
            fill="#1f2937"
            tickFormatter={(value) => `${value}`}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function getGradeTextColor(grade: DifficultyGrade): string {
  switch (grade) {
    case 'S': return 'text-green-400';
    case 'A': return 'text-blue-400';
    case 'B': return 'text-yellow-400';
    case 'C': return 'text-orange-400';
    case 'D': return 'text-red-400';
    default: return 'text-gray-400';
  }
}

export default LevelDistributionChart;

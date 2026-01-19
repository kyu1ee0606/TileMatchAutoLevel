/**
 * Playtest Panel Component
 * 플레이테스트 입력 패널
 */

import { useState } from 'react';
import { ProductionLevel, PlaytestResult } from '../../types/production';
import { Button } from '../ui';

interface PlaytestPanelProps {
  level: ProductionLevel;
  onSubmit: (result: PlaytestResult) => void;
  onSkip?: () => void;
}

export function PlaytestPanel({ level, onSubmit, onSkip }: PlaytestPanelProps) {
  const [cleared, setCleared] = useState(true);
  const [attempts, setAttempts] = useState(1);
  const [timeSeconds, setTimeSeconds] = useState(60);
  const [perceivedDifficulty, setPerceivedDifficulty] = useState<1|2|3|4|5>(3);
  const [funRating, setFunRating] = useState<1|2|3|4|5>(3);
  const [comments, setComments] = useState('');
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);

  const issueOptions = [
    '클리어 불가능',
    '너무 쉬움',
    '너무 어려움',
    '재미없음',
    '기믹 버그',
    '밸런스 문제',
    '목표 불명확',
    '시각적 문제',
  ];

  const handleSubmit = () => {
    const result: PlaytestResult = {
      tester_id: 'default_tester',
      tester_name: '테스터',
      tested_at: new Date().toISOString(),
      cleared,
      attempts,
      time_seconds: timeSeconds,
      perceived_difficulty: perceivedDifficulty,
      fun_rating: funRating,
      comments,
      issues: selectedIssues,
    };

    onSubmit(result);

    // Reset form
    setCleared(true);
    setAttempts(1);
    setTimeSeconds(60);
    setPerceivedDifficulty(3);
    setFunRating(3);
    setComments('');
    setSelectedIssues([]);
  };

  const toggleIssue = (issue: string) => {
    setSelectedIssues(prev =>
      prev.includes(issue)
        ? prev.filter(i => i !== issue)
        : [...prev, issue]
    );
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg space-y-4">
      {/* Level Info */}
      <div className="flex justify-between items-center">
        <h3 className="text-sm font-medium text-white">
          레벨 {level.meta.level_number} 테스트
        </h3>
        <span className={`text-sm px-2 py-0.5 rounded ${
          level.meta.grade === 'S' ? 'bg-green-900 text-green-300' :
          level.meta.grade === 'A' ? 'bg-blue-900 text-blue-300' :
          level.meta.grade === 'B' ? 'bg-yellow-900 text-yellow-300' :
          level.meta.grade === 'C' ? 'bg-orange-900 text-orange-300' :
          'bg-red-900 text-red-300'
        }`}>
          {level.meta.grade}등급
        </span>
      </div>

      {/* Clear Status */}
      <div>
        <label className="block text-xs text-gray-400 mb-2">클리어 여부</label>
        <div className="flex gap-2">
          <button
            onClick={() => setCleared(true)}
            className={`flex-1 py-2 rounded text-sm ${
              cleared
                ? 'bg-green-600 text-white'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            클리어
          </button>
          <button
            onClick={() => setCleared(false)}
            className={`flex-1 py-2 rounded text-sm ${
              !cleared
                ? 'bg-red-600 text-white'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            실패
          </button>
        </div>
      </div>

      {/* Attempts & Time */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1">시도 횟수</label>
          <input
            type="number"
            value={attempts}
            onChange={(e) => setAttempts(Math.max(1, Number(e.target.value)))}
            min={1}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">소요 시간(초)</label>
          <input
            type="number"
            value={timeSeconds}
            onChange={(e) => setTimeSeconds(Math.max(1, Number(e.target.value)))}
            min={1}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
          />
        </div>
      </div>

      {/* Perceived Difficulty */}
      <div>
        <label className="block text-xs text-gray-400 mb-2">체감 난이도</label>
        <div className="flex gap-1">
          {([1, 2, 3, 4, 5] as const).map((val) => (
            <button
              key={val}
              onClick={() => setPerceivedDifficulty(val)}
              className={`flex-1 py-2 rounded text-xs ${
                perceivedDifficulty === val
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-700 text-gray-300'
              }`}
            >
              {val === 1 ? '매우쉬움' :
               val === 2 ? '쉬움' :
               val === 3 ? '보통' :
               val === 4 ? '어려움' : '매우어려움'}
            </button>
          ))}
        </div>
      </div>

      {/* Fun Rating */}
      <div>
        <label className="block text-xs text-gray-400 mb-2">재미 점수</label>
        <div className="flex gap-1">
          {([1, 2, 3, 4, 5] as const).map((val) => (
            <button
              key={val}
              onClick={() => setFunRating(val)}
              className={`flex-1 py-2 rounded text-xs ${
                funRating === val
                  ? 'bg-yellow-600 text-white'
                  : 'bg-gray-700 text-gray-300'
              }`}
            >
              {val === 1 ? '지루' :
               val === 2 ? '별로' :
               val === 3 ? '보통' :
               val === 4 ? '재미' : '최고'}
            </button>
          ))}
        </div>
      </div>

      {/* Issues */}
      <div>
        <label className="block text-xs text-gray-400 mb-2">발견된 문제</label>
        <div className="flex flex-wrap gap-1">
          {issueOptions.map((issue) => (
            <button
              key={issue}
              onClick={() => toggleIssue(issue)}
              className={`px-2 py-1 rounded text-xs ${
                selectedIssues.includes(issue)
                  ? 'bg-red-600 text-white'
                  : 'bg-gray-700 text-gray-300'
              }`}
            >
              {issue}
            </button>
          ))}
        </div>
      </div>

      {/* Comments */}
      <div>
        <label className="block text-xs text-gray-400 mb-1">코멘트</label>
        <textarea
          value={comments}
          onChange={(e) => setComments(e.target.value)}
          placeholder="추가 피드백..."
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm resize-none"
          rows={2}
        />
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <Button onClick={handleSubmit} className="flex-1">
          결과 저장
        </Button>
        {onSkip && (
          <Button onClick={onSkip} variant="secondary">
            건너뛰기
          </Button>
        )}
      </div>
    </div>
  );
}

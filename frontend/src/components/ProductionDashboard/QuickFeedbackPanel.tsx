/**
 * QuickFeedbackPanel
 * 빠른 피드백 버튼 UI - 원클릭 플레이테스트 결과 입력
 * P1: QA 테스터의 피드백 입력 속도 2배 향상
 */

import { useState } from 'react';
import { ProductionLevel, PlaytestResult } from '../../types/production';
import { Button } from '../ui';
import { ChevronRight, ThumbsUp, ThumbsDown, Minus, Star, Moon, Check, Skull, Bug, Scale, HelpCircle } from 'lucide-react';

interface QuickFeedbackPanelProps {
  level: ProductionLevel;
  onSubmit: (result: PlaytestResult) => void;
  onNext?: () => void;
  showDetailedForm?: boolean;
}

type DifficultyChoice = 'easy' | 'normal' | 'hard';
type FunChoice = 'fun' | 'boring';
type ClearChoice = 'clear' | 'fail';
type IssueChoice = 'bug' | 'balance' | 'unclear' | null;

export function QuickFeedbackPanel({ level, onSubmit, onNext, showDetailedForm = false }: QuickFeedbackPanelProps) {
  // Quick selection states
  const [difficulty, setDifficulty] = useState<DifficultyChoice>('normal');
  const [fun, setFun] = useState<FunChoice>('fun');
  const [clearStatus, setClearStatus] = useState<ClearChoice>('clear');
  const [issue, setIssue] = useState<IssueChoice>(null);

  // Optional detailed input (hidden by default)
  const [showDetails, setShowDetails] = useState(showDetailedForm);
  const [attempts, setAttempts] = useState(1);
  const [timeSeconds, setTimeSeconds] = useState(60);
  const [comments, setComments] = useState('');

  const handleSubmitAndNext = () => {
    // Convert quick selections to PlaytestResult
    const perceivedDifficulty: 1|2|3|4|5 =
      difficulty === 'easy' ? 2 :
      difficulty === 'normal' ? 3 : 4;

    const funRating: 1|2|3|4|5 = fun === 'fun' ? 4 : 2;

    const issues: string[] = [];
    if (issue === 'bug') issues.push('기믹 버그');
    if (issue === 'balance') issues.push('밸런스 문제');
    if (issue === 'unclear') issues.push('목표 불명확');
    if (difficulty === 'easy') issues.push('너무 쉬움');
    if (difficulty === 'hard') issues.push('너무 어려움');
    if (clearStatus === 'fail' && !issue) issues.push('클리어 불가능');

    const result: PlaytestResult = {
      tester_id: 'quick_tester',
      tester_name: 'QA',
      tested_at: new Date().toISOString(),
      cleared: clearStatus === 'clear',
      attempts,
      time_seconds: timeSeconds,
      perceived_difficulty: perceivedDifficulty,
      fun_rating: funRating,
      comments,
      issues,
    };

    onSubmit(result);

    // Reset for next level
    setDifficulty('normal');
    setFun('fun');
    setClearStatus('clear');
    setIssue(null);
    setComments('');
    setAttempts(1);
    setTimeSeconds(60);

    // Auto-advance to next level
    onNext?.();
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-white flex items-center gap-2">
          <span className="text-yellow-400">⚡</span> 빠른 피드백
        </h3>
        <span className="text-xs text-gray-400">
          레벨 {level.meta.level_number}
        </span>
      </div>

      {/* Difficulty Selection */}
      <div className="space-y-2">
        <div className="text-xs text-gray-400">난이도 체감</div>
        <div className="flex gap-2">
          <button
            onClick={() => setDifficulty('easy')}
            className={`flex-1 py-3 rounded-lg flex flex-col items-center gap-1 transition-all ${
              difficulty === 'easy'
                ? 'bg-green-600 text-white ring-2 ring-green-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <ThumbsUp className="w-5 h-5" />
            <span className="text-xs">쉬움</span>
          </button>
          <button
            onClick={() => setDifficulty('normal')}
            className={`flex-1 py-3 rounded-lg flex flex-col items-center gap-1 transition-all ${
              difficulty === 'normal'
                ? 'bg-gray-500 text-white ring-2 ring-gray-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Minus className="w-5 h-5" />
            <span className="text-xs">보통</span>
          </button>
          <button
            onClick={() => setDifficulty('hard')}
            className={`flex-1 py-3 rounded-lg flex flex-col items-center gap-1 transition-all ${
              difficulty === 'hard'
                ? 'bg-red-600 text-white ring-2 ring-red-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <ThumbsDown className="w-5 h-5" />
            <span className="text-xs">어려움</span>
          </button>
        </div>
      </div>

      {/* Fun Selection */}
      <div className="space-y-2">
        <div className="text-xs text-gray-400">재미</div>
        <div className="flex gap-2">
          <button
            onClick={() => setFun('fun')}
            className={`flex-1 py-3 rounded-lg flex flex-col items-center gap-1 transition-all ${
              fun === 'fun'
                ? 'bg-yellow-600 text-white ring-2 ring-yellow-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Star className="w-5 h-5" />
            <span className="text-xs">재밌음</span>
          </button>
          <button
            onClick={() => setFun('boring')}
            className={`flex-1 py-3 rounded-lg flex flex-col items-center gap-1 transition-all ${
              fun === 'boring'
                ? 'bg-gray-600 text-white ring-2 ring-gray-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Moon className="w-5 h-5" />
            <span className="text-xs">지루함</span>
          </button>
        </div>
      </div>

      {/* Clear Status */}
      <div className="space-y-2">
        <div className="text-xs text-gray-400">클리어 여부</div>
        <div className="flex gap-2">
          <button
            onClick={() => setClearStatus('clear')}
            className={`flex-1 py-3 rounded-lg flex flex-col items-center gap-1 transition-all ${
              clearStatus === 'clear'
                ? 'bg-green-600 text-white ring-2 ring-green-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Check className="w-5 h-5" />
            <span className="text-xs">클리어</span>
          </button>
          <button
            onClick={() => setClearStatus('fail')}
            className={`flex-1 py-3 rounded-lg flex flex-col items-center gap-1 transition-all ${
              clearStatus === 'fail'
                ? 'bg-red-600 text-white ring-2 ring-red-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Skull className="w-5 h-5" />
            <span className="text-xs">실패</span>
          </button>
        </div>
      </div>

      {/* Issue Selection (Optional) */}
      <div className="space-y-2">
        <div className="text-xs text-gray-400">문제 발견 (선택)</div>
        <div className="flex gap-2">
          <button
            onClick={() => setIssue(issue === 'bug' ? null : 'bug')}
            className={`flex-1 py-2 rounded-lg flex flex-col items-center gap-1 transition-all ${
              issue === 'bug'
                ? 'bg-orange-600 text-white ring-2 ring-orange-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Bug className="w-4 h-4" />
            <span className="text-[10px]">버그</span>
          </button>
          <button
            onClick={() => setIssue(issue === 'balance' ? null : 'balance')}
            className={`flex-1 py-2 rounded-lg flex flex-col items-center gap-1 transition-all ${
              issue === 'balance'
                ? 'bg-purple-600 text-white ring-2 ring-purple-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Scale className="w-4 h-4" />
            <span className="text-[10px]">밸런스</span>
          </button>
          <button
            onClick={() => setIssue(issue === 'unclear' ? null : 'unclear')}
            className={`flex-1 py-2 rounded-lg flex flex-col items-center gap-1 transition-all ${
              issue === 'unclear'
                ? 'bg-blue-600 text-white ring-2 ring-blue-400'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <HelpCircle className="w-4 h-4" />
            <span className="text-[10px]">목표불명확</span>
          </button>
        </div>
      </div>

      {/* Expandable Details */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full py-1 text-xs text-gray-400 hover:text-gray-300 flex items-center justify-center gap-1"
      >
        {showDetails ? '상세 입력 숨기기' : '상세 입력 보기'}
        <ChevronRight className={`w-3 h-3 transition-transform ${showDetails ? 'rotate-90' : ''}`} />
      </button>

      {showDetails && (
        <div className="space-y-3 p-3 bg-gray-700/50 rounded-lg">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">시도 횟수</label>
              <input
                type="number"
                value={attempts}
                onChange={(e) => setAttempts(Math.max(1, Number(e.target.value)))}
                min={1}
                className="w-full px-2 py-1 bg-gray-600 border border-gray-500 rounded text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">소요 시간(초)</label>
              <input
                type="number"
                value={timeSeconds}
                onChange={(e) => setTimeSeconds(Math.max(1, Number(e.target.value)))}
                min={1}
                className="w-full px-2 py-1 bg-gray-600 border border-gray-500 rounded text-sm"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">코멘트</label>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="추가 피드백..."
              className="w-full px-2 py-1 bg-gray-600 border border-gray-500 rounded text-sm resize-none"
              rows={2}
            />
          </div>
        </div>
      )}

      {/* Submit Button */}
      <Button
        onClick={handleSubmitAndNext}
        className="w-full py-3 text-base font-medium flex items-center justify-center gap-2"
      >
        제출 & 다음
        <ChevronRight className="w-5 h-5" />
      </Button>

      {/* Quick Summary */}
      <div className="text-xs text-gray-500 text-center">
        {difficulty === 'easy' ? '👍 쉬움' : difficulty === 'hard' ? '👎 어려움' : '😐 보통'}
        {' • '}
        {fun === 'fun' ? '⭐ 재밌음' : '😴 지루함'}
        {' • '}
        {clearStatus === 'clear' ? '✅ 클리어' : '💀 실패'}
        {issue && ` • ${issue === 'bug' ? '🐛 버그' : issue === 'balance' ? '⚖️ 밸런스' : '❓ 목표불명확'}`}
      </div>
    </div>
  );
}

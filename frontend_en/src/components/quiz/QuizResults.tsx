import React from 'react';
import { CheckCircle, XCircle, SkipForward, RotateCcw, Eye } from 'lucide-react';

interface QuizResultsProps {
  totalQuestions: number;
  correctCount: number;
  wrongCount: number;
  skippedCount: number;
  onReview: () => void;
  onRetake: () => void;
}

export const QuizResults: React.FC<QuizResultsProps> = ({
  totalQuestions,
  correctCount,
  wrongCount,
  skippedCount,
  onReview,
  onRetake,
}) => {
  const percentage = Math.round((correctCount / totalQuestions) * 100);

  const getScoreColor = () => {
    if (percentage >= 80) return 'text-green-600';
    if (percentage >= 60) return 'text-yellow-600';
    return 'text-red-600';
  };

  const getScoreMessage = () => {
    if (percentage >= 80) return 'Excellent! 🎉';
    if (percentage >= 60) return 'Good job! 👍';
    return 'Keep practicing! 💪';
  };

  return (
    <div className="max-w-2xl mx-auto p-8">
      {/* Score Display */}
      <div className="text-center mb-8">
        <h2 className="text-3xl font-bold text-gray-900 mb-2">Quiz Complete!</h2>
        <p className="text-lg text-gray-600">{getScoreMessage()}</p>
      </div>

      {/* Score Circle */}
      <div className="flex justify-center mb-8">
        <div className="relative w-48 h-48">
          <svg className="w-full h-full transform -rotate-90">
            <circle
              cx="96"
              cy="96"
              r="88"
              stroke="#e5e7eb"
              strokeWidth="12"
              fill="none"
            />
            <circle
              cx="96"
              cy="96"
              r="88"
              stroke={percentage >= 80 ? '#10b981' : percentage >= 60 ? '#f59e0b' : '#ef4444'}
              strokeWidth="12"
              fill="none"
              strokeDasharray={`${2 * Math.PI * 88}`}
              strokeDashoffset={`${2 * Math.PI * 88 * (1 - percentage / 100)}`}
              strokeLinecap="round"
              className="transition-all duration-1000"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className={`text-5xl font-bold ${getScoreColor()}`}>
                {percentage}%
              </div>
              <div className="text-sm text-gray-500 mt-1">
                {correctCount}/{totalQuestions}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Statistics */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
          <CheckCircle className="w-8 h-8 text-green-600 mx-auto mb-2" />
          <div className="text-2xl font-bold text-green-700">{correctCount}</div>
          <div className="text-sm text-green-600">Correct</div>
        </div>

        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center">
          <XCircle className="w-8 h-8 text-red-600 mx-auto mb-2" />
          <div className="text-2xl font-bold text-red-700">{wrongCount}</div>
          <div className="text-sm text-red-600">Wrong</div>
        </div>

        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
          <SkipForward className="w-8 h-8 text-gray-600 mx-auto mb-2" />
          <div className="text-2xl font-bold text-gray-700">{skippedCount}</div>
          <div className="text-sm text-gray-600">Skipped</div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-4">
        <button
          onClick={onReview}
          className="flex-1 bg-blue-600 text-white py-3 px-6 rounded-lg hover:bg-blue-700 transition-colors flex items-center justify-center gap-2 font-medium"
        >
          <Eye className="w-5 h-5" />
          Review Quiz
        </button>

        <button
          onClick={onRetake}
          className="flex-1 bg-gray-600 text-white py-3 px-6 rounded-lg hover:bg-gray-700 transition-colors flex items-center justify-center gap-2 font-medium"
        >
          <RotateCcw className="w-5 h-5" />
          Retake Quiz
        </button>
      </div>
    </div>
  );
};

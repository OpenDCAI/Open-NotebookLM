import React from 'react';
import { motion } from 'framer-motion';
import { RotateCcw, Eye } from 'lucide-react';

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
    if (percentage >= 80) return '#34C759';
    if (percentage >= 60) return '#FF9500';
    return '#FF3B30';
  };

  const getScoreTextColor = () => {
    if (percentage >= 80) return 'text-green-600';
    if (percentage >= 60) return 'text-orange-500';
    return 'text-red-500';
  };

  const getScoreMessage = () => {
    if (percentage >= 80) return 'Excellent!';
    if (percentage >= 60) return 'Good job!';
    return 'Keep practicing!';
  };

  const circumference = 2 * Math.PI * 88;

  return (
    <div className="max-w-2xl mx-auto p-8">
      {/* Score Display */}
      <div className="text-center mb-8">
        <motion.h2
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-2xl font-semibold text-ios-gray-900 mb-2"
        >
          Quiz Complete!
        </motion.h2>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="text-lg text-ios-gray-500"
        >
          {getScoreMessage()}
        </motion.p>
      </div>

      {/* Score Circle */}
      <div className="flex justify-center mb-8">
        <motion.div
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 200, damping: 20, delay: 0.1 }}
          className="relative w-48 h-48"
        >
          <svg className="w-full h-full transform -rotate-90">
            <circle
              cx="96"
              cy="96"
              r="88"
              stroke="#e5e5ea"
              strokeWidth="10"
              fill="none"
            />
            <motion.circle
              cx="96"
              cy="96"
              r="88"
              stroke={getScoreColor()}
              strokeWidth="10"
              fill="none"
              strokeLinecap="round"
              initial={{ strokeDasharray: circumference, strokeDashoffset: circumference }}
              animate={{ strokeDashoffset: circumference * (1 - percentage / 100) }}
              transition={{ type: 'spring', stiffness: 60, damping: 15, delay: 0.3 }}
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <motion.div
                initial={{ opacity: 0, scale: 0.5 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.5, type: 'spring', stiffness: 200 }}
                className={`text-5xl font-bold ${getScoreTextColor()}`}
              >
                {percentage}%
              </motion.div>
              <div className="text-sm text-ios-gray-400 mt-1">
                {correctCount}/{totalQuestions}
              </div>
            </div>
          </div>
        </motion.div>
      </div>

      {/* Statistics */}
      <div className="grid grid-cols-3 gap-3 mb-8">
        {[
          { label: 'Correct', count: correctCount, color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-100' },
          { label: 'Wrong', count: wrongCount, color: 'text-red-500', bg: 'bg-red-50', border: 'border-red-100' },
          { label: 'Skipped', count: skippedCount, color: 'text-ios-gray-500', bg: 'bg-ios-gray-50', border: 'border-ios-gray-100' },
        ].map((stat, idx) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4 + idx * 0.1 }}
            className={`${stat.bg} border ${stat.border} rounded-ios-lg p-4 text-center shadow-ios-sm`}
          >
            <div className={`text-2xl font-bold ${stat.color}`}>{stat.count}</div>
            <div className={`text-xs font-medium ${stat.color} mt-1`}>{stat.label}</div>
          </motion.div>
        ))}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        <motion.button
          whileTap={{ scale: 0.97 }}
          onClick={onReview}
          className="flex-1 bg-primary text-white py-3 px-6 rounded-ios-lg hover:bg-primary/90 transition-colors flex items-center justify-center gap-2 font-medium shadow-ios-sm"
        >
          <Eye className="w-5 h-5" />
          Review Quiz
        </motion.button>

        <motion.button
          whileTap={{ scale: 0.97 }}
          onClick={onRetake}
          className="flex-1 bg-ios-gray-100 text-ios-gray-700 py-3 px-6 rounded-ios-lg hover:bg-ios-gray-200 transition-colors flex items-center justify-center gap-2 font-medium"
        >
          <RotateCcw className="w-5 h-5" />
          Retake Quiz
        </motion.button>
      </div>
    </div>
  );
};

import React from 'react';
import { CheckCircle, XCircle, Circle } from 'lucide-react';

interface QuizOption {
  label: string;
  text: string;
}

interface QuizQuestionProps {
  question: string;
  options: QuizOption[];
  selectedAnswer: string | null;
  onSelectAnswer: (answer: string) => void;
  showResult?: boolean;
  correctAnswer?: string;
  isCorrect?: boolean;
}

export const QuizQuestion: React.FC<QuizQuestionProps> = ({
  question,
  options,
  selectedAnswer,
  onSelectAnswer,
  showResult = false,
  correctAnswer,
  isCorrect,
}) => {
  const getOptionStyle = (optionLabel: string) => {
    if (!showResult) {
      // 答题模式
      if (selectedAnswer === optionLabel) {
        return 'border-blue-500 bg-blue-50';
      }
      return 'border-gray-300 hover:border-blue-400 hover:bg-gray-50';
    } else {
      // 结果展示模式
      if (optionLabel === correctAnswer) {
        return 'border-green-500 bg-green-50';
      }
      if (selectedAnswer === optionLabel && !isCorrect) {
        return 'border-red-500 bg-red-50';
      }
      return 'border-gray-300 bg-gray-50';
    }
  };

  const getOptionIcon = (optionLabel: string) => {
    if (!showResult) {
      return selectedAnswer === optionLabel ? (
        <CheckCircle className="w-5 h-5 text-blue-600" />
      ) : (
        <Circle className="w-5 h-5 text-gray-400" />
      );
    } else {
      if (optionLabel === correctAnswer) {
        return <CheckCircle className="w-5 h-5 text-green-600" />;
      }
      if (selectedAnswer === optionLabel && !isCorrect) {
        return <XCircle className="w-5 h-5 text-red-600" />;
      }
      return <Circle className="w-5 h-5 text-gray-400" />;
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium text-gray-900">{question}</h3>

      <div className="space-y-3">
        {options.map((option) => (
          <button
            key={option.label}
            onClick={() => !showResult && onSelectAnswer(option.label)}
            disabled={showResult}
            className={`w-full p-4 rounded-lg border-2 transition-all text-left flex items-start gap-3 ${getOptionStyle(option.label)} ${
              showResult ? 'cursor-default' : 'cursor-pointer'
            }`}
          >
            {getOptionIcon(option.label)}
            <div className="flex-1">
              <span className="font-medium text-gray-700">{option.label}.</span>{' '}
              <span className="text-gray-900">{option.text}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};

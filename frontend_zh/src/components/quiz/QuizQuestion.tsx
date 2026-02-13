import React from 'react';
import { motion } from 'framer-motion';

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
      if (selectedAnswer === optionLabel) {
        return 'border-primary bg-primary/5 shadow-ios-sm';
      }
      return 'border-ios-gray-200 hover:border-primary/40 hover:bg-ios-gray-50';
    } else {
      if (optionLabel === correctAnswer) {
        return 'border-green-500 bg-green-50 shadow-ios-sm';
      }
      if (selectedAnswer === optionLabel && !isCorrect) {
        return 'border-red-500 bg-red-50';
      }
      return 'border-ios-gray-200 bg-ios-gray-50';
    }
  };

  const getRadioStyle = (optionLabel: string) => {
    if (!showResult) {
      if (selectedAnswer === optionLabel) {
        return (
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 400, damping: 15 }}
            className="w-5 h-5 rounded-full bg-primary flex items-center justify-center"
          >
            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </motion.div>
        );
      }
      return <div className="w-5 h-5 rounded-full border-2 border-ios-gray-300" />;
    } else {
      if (optionLabel === correctAnswer) {
        return (
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 400, damping: 15 }}
            className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center"
          >
            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </motion.div>
        );
      }
      if (selectedAnswer === optionLabel && !isCorrect) {
        return (
          <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center">
            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
        );
      }
      return <div className="w-5 h-5 rounded-full border-2 border-ios-gray-300" />;
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium text-ios-gray-900">{question}</h3>

      <div className="space-y-3">
        {options.map((option) => (
          <motion.button
            key={option.label}
            whileHover={!showResult ? { scale: 1.01 } : {}}
            whileTap={!showResult ? { scale: 0.98 } : {}}
            onClick={() => !showResult && onSelectAnswer(option.label)}
            disabled={showResult}
            className={`w-full p-4 rounded-ios-lg border-2 transition-all text-left flex items-start gap-3 ${getOptionStyle(option.label)} ${
              showResult ? 'cursor-default' : 'cursor-pointer'
            }`}
          >
            {getRadioStyle(option.label)}
            <div className="flex-1">
              <span className="font-medium text-ios-gray-600">{option.label}.</span>{' '}
              <span className="text-ios-gray-900">{option.text}</span>
            </div>
          </motion.button>
        ))}
      </div>
    </div>
  );
};

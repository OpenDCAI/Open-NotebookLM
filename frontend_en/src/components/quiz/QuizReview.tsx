import React, { useState } from 'react';
import { ChevronLeft, ChevronRight, CheckCircle, XCircle, SkipForward, X } from 'lucide-react';
import { QuizQuestion } from './QuizQuestion';

interface QuizOption {
  label: string;
  text: string;
}

interface Question {
  id: string;
  question: string;
  options: QuizOption[];
  correct_answer: string;
  explanation: string;
  source_excerpt?: string;
}

interface QuizReviewProps {
  questions: Question[];
  userAnswers: Record<string, string | null>;
  onClose: () => void;
}

export const QuizReview: React.FC<QuizReviewProps> = ({
  questions,
  userAnswers,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const currentQuestion = questions[currentIndex];
  const userAnswer = userAnswers[currentQuestion.id];

  const getAnswerStatus = () => {
    if (!userAnswer) return 'skipped';
    return userAnswer === currentQuestion.correct_answer ? 'correct' : 'wrong';
  };

  const handleNext = () => {
    if (currentIndex < questions.length - 1) {
      setCurrentIndex(currentIndex + 1);
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
    }
  };

  const answerStatus = getAnswerStatus();

  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Quiz Review</h2>
        <button
          onClick={onClose}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Progress */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-gray-600">
            Question {currentIndex + 1} of {questions.length}
          </span>
          <div className="flex items-center gap-2">
            {answerStatus === 'correct' && (
              <span className="flex items-center gap-1 text-sm text-green-600">
                <CheckCircle className="w-4 h-4" />
                Correct
              </span>
            )}
            {answerStatus === 'wrong' && (
              <span className="flex items-center gap-1 text-sm text-red-600">
                <XCircle className="w-4 h-4" />
                Wrong
              </span>
            )}
            {answerStatus === 'skipped' && (
              <span className="flex items-center gap-1 text-sm text-gray-600">
                <SkipForward className="w-4 h-4" />
                Skipped
              </span>
            )}
          </div>
        </div>
        <div className="w-full bg-gray-200 h-2 rounded-full">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all"
            style={{ width: `${((currentIndex + 1) / questions.length) * 100}%` }}
          />
        </div>
      </div>

      {/* Question */}
      <div className="bg-white border border-gray-200 rounded-lg p-6 mb-6">
        <QuizQuestion
          question={currentQuestion.question}
          options={currentQuestion.options}
          selectedAnswer={userAnswer}
          onSelectAnswer={() => {}}
          showResult={true}
          correctAnswer={currentQuestion.correct_answer}
          isCorrect={answerStatus === 'correct'}
        />
      </div>

      {/* Explanation */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 mb-6">
        <h3 className="font-semibold text-blue-900 mb-2">Explanation</h3>
        <p className="text-blue-800 mb-4">{currentQuestion.explanation}</p>

        {currentQuestion.source_excerpt && (
          <div className="bg-white rounded p-4 border border-blue-100">
            <p className="text-xs text-blue-600 mb-1">Source:</p>
            <p className="text-sm text-gray-700 italic">{currentQuestion.source_excerpt}</p>
          </div>
        )}
      </div>

      {/* Navigation */}
      <div className="flex justify-between">
        <button
          onClick={handlePrevious}
          disabled={currentIndex === 0}
          className="flex items-center gap-2 px-4 py-2 bg-gray-200 rounded-lg hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Previous
        </button>

        <button
          onClick={handleNext}
          disabled={currentIndex === questions.length - 1}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Next
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};

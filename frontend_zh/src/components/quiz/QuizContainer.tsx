import React, { useState } from 'react';
import { QuizQuestion } from './QuizQuestion';
import { QuizResults } from './QuizResults';
import { QuizReview } from './QuizReview';
import { ChevronLeft, ChevronRight, SkipForward } from 'lucide-react';

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

interface QuizContainerProps {
  questions: Question[];
  onClose: () => void;
}

type QuizState = 'taking' | 'results' | 'review';

export const QuizContainer: React.FC<QuizContainerProps> = ({
  questions,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [userAnswers, setUserAnswers] = useState<Record<string, string | null>>({});
  const [quizState, setQuizState] = useState<QuizState>('taking');

  const currentQuestion = questions[currentIndex];
  const currentAnswer = userAnswers[currentQuestion?.id] || null;

  const handleSelectAnswer = (answer: string) => {
    setUserAnswers({
      ...userAnswers,
      [currentQuestion.id]: answer,
    });
  };

  const handleSkip = () => {
    setUserAnswers({
      ...userAnswers,
      [currentQuestion.id]: null,
    });
    handleNext();
  };

  const handleNext = () => {
    if (currentIndex < questions.length - 1) {
      setCurrentIndex(currentIndex + 1);
    } else {
      // 最后一题，显示结果
      setQuizState('results');
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
    }
  };

  const handleRetake = () => {
    setCurrentIndex(0);
    setUserAnswers({});
    setQuizState('taking');
  };

  const handleReview = () => {
    setQuizState('review');
  };

  // 计算统计数据
  const calculateStats = () => {
    let correct = 0;
    let wrong = 0;
    let skipped = 0;

    questions.forEach((q) => {
      const answer = userAnswers[q.id];
      if (!answer) {
        skipped++;
      } else if (answer === q.correct_answer) {
        correct++;
      } else {
        wrong++;
      }
    });

    return { correct, wrong, skipped };
  };

  // 结果页面
  if (quizState === 'results') {
    const stats = calculateStats();
    return (
      <QuizResults
        totalQuestions={questions.length}
        correctCount={stats.correct}
        wrongCount={stats.wrong}
        skippedCount={stats.skipped}
        onReview={handleReview}
        onRetake={handleRetake}
      />
    );
  }

  // 复习页面
  if (quizState === 'review') {
    return (
      <QuizReview
        questions={questions}
        userAnswers={userAnswers}
        onClose={onClose}
      />
    );
  }

  // 答题页面
  return (
    <div className="max-w-3xl mx-auto p-6">
      {/* Progress */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-gray-600">
            Question {currentIndex + 1} of {questions.length}
          </span>
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
          selectedAnswer={currentAnswer}
          onSelectAnswer={handleSelectAnswer}
        />
      </div>

      {/* Navigation */}
      <div className="flex justify-between items-center">
        <button
          onClick={handlePrevious}
          disabled={currentIndex === 0}
          className="flex items-center gap-2 px-4 py-2 bg-gray-200 rounded-lg hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Previous
        </button>

        <button
          onClick={handleSkip}
          className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <SkipForward className="w-4 h-4" />
          Skip
        </button>

        <button
          onClick={handleNext}
          disabled={!currentAnswer}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {currentIndex === questions.length - 1 ? 'Finish' : 'Next'}
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};

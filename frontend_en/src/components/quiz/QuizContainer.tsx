import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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

const springTransition = { type: 'spring', stiffness: 300, damping: 30 };

export const QuizContainer: React.FC<QuizContainerProps> = ({
  questions,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [userAnswers, setUserAnswers] = useState<Record<string, string | null>>({});
  const [quizState, setQuizState] = useState<QuizState>('taking');
  const [direction, setDirection] = useState(1);

  const currentQuestion = questions[currentIndex];
  const currentAnswer = userAnswers[currentQuestion?.id] || null;
  const progress = ((currentIndex + 1) / questions.length) * 100;

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
      setDirection(1);
      setCurrentIndex(currentIndex + 1);
    } else {
      setQuizState('results');
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setDirection(-1);
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

  if (quizState === 'review') {
    return (
      <QuizReview
        questions={questions}
        userAnswers={userAnswers}
        onClose={onClose}
      />
    );
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      {/* iOS Progress Bar */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-ios-gray-500">
            Question {currentIndex + 1} of {questions.length}
          </span>
        </div>
        <div className="w-full bg-ios-gray-100 h-1 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-primary rounded-full"
            initial={false}
            animate={{ width: `${progress}%` }}
            transition={springTransition}
          />
        </div>
      </div>

      {/* Question with spring transition */}
      <AnimatePresence mode="wait" custom={direction}>
        <motion.div
          key={currentIndex}
          custom={direction}
          initial={{ x: direction > 0 ? 30 : -30, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: direction > 0 ? -30 : 30, opacity: 0 }}
          transition={springTransition}
          className="bg-white border border-ios-gray-100 rounded-ios-lg p-6 mb-6 shadow-ios-sm"
        >
          <QuizQuestion
            question={currentQuestion.question}
            options={currentQuestion.options}
            selectedAnswer={currentAnswer}
            onSelectAnswer={handleSelectAnswer}
          />
        </motion.div>
      </AnimatePresence>

      {/* Navigation */}
      <div className="flex justify-between items-center">
        <motion.button
          whileTap={{ scale: 0.95 }}
          onClick={handlePrevious}
          disabled={currentIndex === 0}
          className="flex items-center gap-2 px-4 py-2.5 bg-ios-gray-100 rounded-ios-lg text-sm font-medium text-ios-gray-700 hover:bg-ios-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Previous
        </motion.button>

        <motion.button
          whileTap={{ scale: 0.95 }}
          onClick={handleSkip}
          className="flex items-center gap-2 px-4 py-2.5 border border-ios-gray-200 rounded-ios-lg text-sm font-medium text-ios-gray-600 hover:bg-ios-gray-50 transition-colors"
        >
          <SkipForward className="w-4 h-4" />
          Skip
        </motion.button>

        <motion.button
          whileTap={{ scale: 0.95 }}
          onClick={handleNext}
          disabled={!currentAnswer}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-ios-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {currentIndex === questions.length - 1 ? 'Finish' : 'Next'}
          <ChevronRight className="w-4 h-4" />
        </motion.button>
      </div>
    </div>
  );
};

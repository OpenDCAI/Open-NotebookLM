import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { RotateCw, ChevronLeft, ChevronRight } from 'lucide-react';

interface Flashcard {
  id: string;
  question: string;
  answer: string;
  type: string;
  source_excerpt?: string;
}

interface FlashcardViewerProps {
  flashcards: Flashcard[];
  onClose: () => void;
}

const springFlip = { type: 'spring', stiffness: 300, damping: 25 };

export const FlashcardViewer: React.FC<FlashcardViewerProps> = ({
  flashcards,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);

  const currentCard = flashcards[currentIndex];
  const progress = ((currentIndex + 1) / flashcards.length) * 100;

  const handleNext = () => {
    if (currentIndex < flashcards.length - 1) {
      setCurrentIndex(currentIndex + 1);
      setIsFlipped(false);
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
      setIsFlipped(false);
    }
  };

  const handleFlip = () => {
    setIsFlipped(!isFlipped);
  };

  return (
    <div className="max-w-3xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-ios-gray-900">Flashcard Study</h2>
        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={onClose}
          className="px-4 py-2 text-ios-gray-500 hover:text-ios-gray-700 rounded-ios text-sm font-medium"
        >
          Close
        </motion.button>
      </div>

      {/* iOS Progress Bar */}
      <div className="text-center mb-6">
        <p className="text-sm text-ios-gray-500 mb-2">
          {currentIndex + 1} / {flashcards.length}
        </p>
        <div className="w-full bg-ios-gray-100 h-1 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-primary rounded-full"
            initial={false}
            animate={{ width: `${progress}%` }}
            transition={springFlip}
          />
        </div>
      </div>

      {/* Card Area */}
      <div className="mb-8">
        <div
          className="relative h-80 cursor-pointer"
          onClick={handleFlip}
          style={{ perspective: '1000px' }}
        >
          <motion.div
            className="absolute w-full h-full"
            animate={{ rotateY: isFlipped ? 180 : 0 }}
            transition={springFlip}
            style={{ transformStyle: 'preserve-3d' }}
          >
            {/* Front - Question */}
            <div
              className="absolute w-full h-full bg-white rounded-ios-2xl p-8 flex flex-col items-center justify-center shadow-ios-lg border border-ios-gray-100"
              style={{ backfaceVisibility: 'hidden' }}
            >
              <p className="text-2xl text-center font-medium text-ios-gray-900">{currentCard.question}</p>
              <div className="mt-6 flex items-center gap-2 text-ios-gray-400">
                <RotateCw className="w-4 h-4" />
                <span className="text-sm">Click to flip and see answer</span>
              </div>
            </div>

            {/* Back - Answer */}
            <div
              className="absolute w-full h-full bg-gradient-to-br from-primary/5 to-primary/10 rounded-ios-2xl p-8 flex flex-col items-center justify-center shadow-ios-lg border border-primary/20"
              style={{
                backfaceVisibility: 'hidden',
                transform: 'rotateY(180deg)',
              }}
            >
              <p className="text-xl text-center text-ios-gray-800">{currentCard.answer}</p>
              {currentCard.source_excerpt && (
                <div className="mt-6 p-4 bg-white/80 rounded-ios border border-ios-gray-100">
                  <p className="text-xs text-ios-gray-500">Source Excerpt:</p>
                  <p className="text-sm text-ios-gray-600 mt-1">{currentCard.source_excerpt}</p>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      </div>

      {/* Navigation Buttons */}
      <div className="flex justify-between items-center">
        <motion.button
          whileTap={{ scale: 0.95 }}
          onClick={handlePrevious}
          disabled={currentIndex === 0}
          className="flex items-center gap-2 px-5 py-2.5 bg-ios-gray-100 rounded-ios-xl text-sm font-medium text-ios-gray-700 hover:bg-ios-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Previous
        </motion.button>

        <motion.button
          whileTap={{ scale: 0.95 }}
          onClick={handleNext}
          disabled={currentIndex === flashcards.length - 1}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-ios-xl text-sm font-medium hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Next
          <ChevronRight className="w-4 h-4" />
        </motion.button>
      </div>
    </div>
  );
};

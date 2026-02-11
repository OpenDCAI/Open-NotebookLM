import React, { useState } from 'react';
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

export const FlashcardViewer: React.FC<FlashcardViewerProps> = ({
  flashcards,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);

  const currentCard = flashcards[currentIndex];

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
        <h2 className="text-2xl font-bold">Flashcard Study</h2>
        <button
          onClick={onClose}
          className="px-4 py-2 text-gray-600 hover:text-gray-800"
        >
          Close
        </button>
      </div>

      {/* Progress Indicator */}
      <div className="text-center mb-6">
        <p className="text-sm text-gray-600">
          {currentIndex + 1} / {flashcards.length}
        </p>
        <div className="w-full bg-gray-200 h-2 rounded-full mt-2">
          <div
            className="bg-purple-600 h-2 rounded-full transition-all"
            style={{ width: `${((currentIndex + 1) / flashcards.length) * 100}%` }}
          />
        </div>
      </div>

      {/* 卡片区域 */}
      <div className="mb-8">
        <div
          className="relative h-80 cursor-pointer"
          onClick={handleFlip}
          style={{ perspective: '1000px' }}
        >
          <div
            className={`absolute w-full h-full transition-transform duration-500`}
            style={{
              transformStyle: 'preserve-3d',
              transform: isFlipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
            }}
          >
            {/* Front - Question */}
            <div
              className="absolute w-full h-full bg-white border-2 border-purple-500 rounded-lg p-8 flex flex-col items-center justify-center shadow-lg"
              style={{ backfaceVisibility: 'hidden' }}
            >
              <p className="text-2xl text-center font-medium">{currentCard.question}</p>
              <div className="mt-6 flex items-center gap-2 text-gray-500">
                <RotateCw className="w-4 h-4" />
                <span className="text-sm">Click to flip and see answer</span>
              </div>
            </div>

            {/* Back - Answer */}
            <div
              className="absolute w-full h-full bg-purple-50 border-2 border-purple-500 rounded-lg p-8 flex flex-col items-center justify-center shadow-lg"
              style={{
                backfaceVisibility: 'hidden',
                transform: 'rotateY(180deg)',
              }}
            >
              <p className="text-xl text-center">{currentCard.answer}</p>
              {currentCard.source_excerpt && (
                <div className="mt-6 p-4 bg-white rounded border border-purple-200">
                  <p className="text-xs text-gray-600">Source Excerpt:</p>
                  <p className="text-sm text-gray-700 mt-1">{currentCard.source_excerpt}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Navigation Buttons */}
      <div className="flex justify-between items-center">
        <button
          onClick={handlePrevious}
          disabled={currentIndex === 0}
          className="flex items-center gap-2 px-4 py-2 bg-gray-200 rounded-md hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <ChevronLeft className="w-4 h-4" />
          Previous
        </button>

        <button
          onClick={handleNext}
          disabled={currentIndex === flashcards.length - 1}
          className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Next
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};

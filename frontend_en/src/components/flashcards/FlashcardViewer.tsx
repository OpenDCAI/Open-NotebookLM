import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { RotateCw, ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react';

interface CitationReference {
  fileName?: string;
  filePath?: string;
  preview?: string;
  chunkIndex?: number | null;
  sourceNumber?: string;
}

interface FlashcardCitation {
  source_number?: number;
  file_name?: string | null;
  file_path?: string | null;
  preview?: string | null;
  chunk_index?: number | null;
}

interface Flashcard {
  id: string;
  question: string;
  answer: string;
  type: string;
  difficulty?: string | null;
  source_excerpt?: string;
  source_file?: string | null;
  citations?: FlashcardCitation[];
}

interface FlashcardViewerProps {
  flashcards: Flashcard[];
  generationConfig?: {
    difficulty_level?: 'basic' | 'intermediate' | 'advanced' | null;
    card_count?: number | null;
    topic?: string | null;
    test_focus?: string | null;
    generated_at?: string | null;
  } | null;
  onOpenCitation?: (reference: CitationReference) => void;
  onClose: () => void;
}

const springFlip = { type: 'spring', stiffness: 280, damping: 24 };

const difficultyLabelMap: Record<string, string> = {
  basic: 'Basic',
  intermediate: 'Intermediate',
  advanced: 'Advanced',
};

function normalizeCitations(card: Flashcard) {
  const raw = Array.isArray(card.citations) ? card.citations : [];
  if (raw.length > 0) {
    return raw
      .map((item) => ({
        sourceNumber:
          item?.source_number !== undefined && item?.source_number !== null ? String(item.source_number) : '',
        fileName: item?.file_name || undefined,
        filePath: item?.file_path || undefined,
        preview: item?.preview || card.source_excerpt || undefined,
        chunkIndex: item?.chunk_index ?? null,
      }))
      .filter((item) => item.sourceNumber);
  }
  const numbers = Array.from(new Set([...String(card.answer || '').matchAll(/\[(\d+)\]/g)].map((match) => match[1])));
  return numbers.map((sourceNumber) => ({
    sourceNumber,
    fileName: card.source_file || undefined,
    preview: card.source_excerpt || undefined,
    chunkIndex: null,
  }));
}

function renderAnswer(
  answer: string,
  citations: ReturnType<typeof normalizeCitations>,
  activeCitation: string | null,
  onSelect: (value: string) => void,
) {
  const citationSet = new Set(citations.map((item) => item.sourceNumber));
  return answer.split(/(\[\d+\])/g).map((part, index) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (!match || !citationSet.has(match[1])) return <React.Fragment key={`part_${index}`}>{part}</React.Fragment>;
    return (
      <button
        key={`citation_${match[1]}_${index}`}
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onSelect(match[1]);
        }}
        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold mx-0.5 ${
          activeCitation === match[1] ? 'bg-blue-200 text-blue-800' : 'bg-blue-100 text-blue-700'
        }`}
      >
        [{match[1]}]
      </button>
    );
  });
}

export const FlashcardViewer: React.FC<FlashcardViewerProps> = ({
  flashcards,
  generationConfig,
  onOpenCitation,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);

  const currentCard = flashcards[currentIndex];
  const progress = ((currentIndex + 1) / flashcards.length) * 100;
  const citations = useMemo(() => normalizeCitations(currentCard), [currentCard]);
  const selectedCitation = citations.find((item) => item.sourceNumber === activeCitation) || citations[0] || null;

  useEffect(() => {
    setActiveCitation(citations[0]?.sourceNumber || null);
  }, [currentIndex, citations]);

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

  return (
    <div className="max-w-4xl mx-auto p-6">
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

      {generationConfig ? (
        <div className="mb-5 rounded-3xl border border-sky-100 bg-gradient-to-br from-sky-50 via-white to-indigo-50 p-4">
          <div className="flex items-center justify-between gap-3 mb-2">
            <strong className="text-sm text-ios-gray-900">Generation Settings</strong>
            {generationConfig.generated_at ? <span className="text-xs text-ios-gray-500">{generationConfig.generated_at}</span> : null}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-ios-gray-600">
            <span>Difficulty: {difficultyLabelMap[generationConfig.difficulty_level || ''] || 'Default'}</span>
            {generationConfig.card_count ? <span>Card count: {generationConfig.card_count}</span> : null}
            {generationConfig.topic ? <span>Topic: {generationConfig.topic}</span> : null}
            {generationConfig.test_focus ? <span>Focus: {generationConfig.test_focus}</span> : null}
          </div>
        </div>
      ) : null}

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

      <div className="mb-8">
        <div
          className="relative h-[34rem] cursor-pointer"
          onClick={() => setIsFlipped(!isFlipped)}
          style={{ perspective: '1400px' }}
        >
          <motion.div
            className="absolute w-full h-full"
            animate={{ rotateY: isFlipped ? 180 : 0 }}
            transition={springFlip}
            style={{ transformStyle: 'preserve-3d' }}
          >
            <div
              className="absolute w-full h-full rounded-[32px] p-8 flex flex-col shadow-[0_30px_80px_rgba(15,23,42,0.16)] border border-white/60 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.7),rgba(255,255,255,0)_30%),linear-gradient(145deg,rgba(248,250,252,0.98),rgba(226,232,240,0.95))]"
              style={{ backfaceVisibility: 'hidden' }}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="inline-flex rounded-full bg-white/80 px-3 py-1 text-xs font-semibold text-ios-gray-700">
                  {currentCard.type === 'fill_blank' ? 'Fill Blank' : currentCard.type === 'concept' ? 'Concept' : 'Q&A'}
                </span>
                <span className="inline-flex rounded-full bg-slate-900 text-white px-3 py-1 text-xs font-semibold">
                  {difficultyLabelMap[String(currentCard.difficulty || generationConfig?.difficulty_level || '').toLowerCase()] || 'Flexible'}
                </span>
              </div>
              <div className="mt-10 text-6xl font-bold tracking-tight text-slate-200">#{String(currentIndex + 1).padStart(2, '0')}</div>
              <p className="mt-4 text-3xl leading-relaxed font-medium text-ios-gray-900">{currentCard.question}</p>
              <div className="mt-auto flex items-center gap-2 text-ios-gray-400">
                <RotateCw className="w-4 h-4" />
                <span className="text-sm">Click to flip and see answer</span>
              </div>
            </div>

            <div
              className="absolute w-full h-full rounded-[32px] p-8 flex flex-col shadow-[0_30px_80px_rgba(15,23,42,0.16)] border border-white/50 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.55),rgba(255,255,255,0)_26%),linear-gradient(145deg,rgba(224,231,255,0.95),rgba(238,242,255,0.92))]"
              style={{ backfaceVisibility: 'hidden', transform: 'rotateY(180deg)' }}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="inline-flex rounded-full bg-white/80 px-3 py-1 text-xs font-semibold text-ios-gray-700">Answer</span>
                {currentCard.source_file ? (
                  <span className="inline-flex rounded-full bg-white/80 px-3 py-1 text-xs font-semibold text-ios-gray-700">
                    {currentCard.source_file}
                  </span>
                ) : null}
              </div>
              <div className="mt-5">
                <p className="text-lg leading-8 text-ios-gray-800">
                  {renderAnswer(String(currentCard.answer || ''), citations, activeCitation, setActiveCitation)}
                </p>
              </div>
              {selectedCitation ? (
                <div className="mt-6 flex flex-col gap-3">
                  <div className="flex flex-wrap gap-2">
                    {citations.map((citation) => (
                      <button
                        key={citation.sourceNumber}
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setActiveCitation(citation.sourceNumber);
                        }}
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${
                          selectedCitation.sourceNumber === citation.sourceNumber
                            ? 'bg-blue-600 text-white'
                            : 'bg-white/80 text-ios-gray-700'
                        }`}
                      >
                        [{citation.sourceNumber}]
                      </button>
                    ))}
                  </div>
                  <div className="rounded-2xl border border-white/60 bg-white/75 p-4">
                    <p className="text-sm font-semibold text-ios-gray-900">{selectedCitation.fileName || `Source [${selectedCitation.sourceNumber}]`}</p>
                    <p className="mt-2 text-sm leading-6 text-ios-gray-600">{selectedCitation.preview || currentCard.source_excerpt || 'No preview available.'}</p>
                    {onOpenCitation ? (
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          onOpenCitation({
                            fileName: selectedCitation.fileName,
                            filePath: selectedCitation.filePath,
                            preview: selectedCitation.preview,
                            chunkIndex: selectedCitation.chunkIndex,
                            sourceNumber: selectedCitation.sourceNumber,
                          });
                        }}
                        className="mt-3 inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-xs font-semibold text-white"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        Open Full Source
                      </button>
                    ) : null}
                  </div>
                </div>
              ) : currentCard.source_excerpt ? (
                <div className="mt-6 p-4 bg-white/80 rounded-ios border border-ios-gray-100">
                  <p className="text-xs text-ios-gray-500">Source Excerpt:</p>
                  <p className="text-sm text-ios-gray-600 mt-1">{currentCard.source_excerpt}</p>
                </div>
              ) : null}
            </div>
          </motion.div>
        </div>
      </div>

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

import React, { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, ExternalLink, RotateCw } from 'lucide-react';
import type { CitationReference, FlashcardGenerationConfig, FlashcardItem } from './thinkflow-types';

type Props = {
  cards: FlashcardItem[];
  generationConfig?: FlashcardGenerationConfig | null;
  onOpenCitation?: (reference: CitationReference) => void;
};

type CitationMeta = {
  sourceNumber: string;
  fileName?: string;
  filePath?: string;
  preview?: string;
  chunkIndex?: number | null;
};

const difficultyLabelMap: Record<string, string> = {
  basic: '基础',
  intermediate: '进阶',
  advanced: '挑战',
};

const difficultyToneMap: Record<string, string> = {
  basic: 'is-basic',
  intermediate: 'is-intermediate',
  advanced: 'is-advanced',
};

function getCardKindLabel(type?: string) {
  if (type === 'fill_blank') return '填空卡';
  if (type === 'concept') return '概念卡';
  return '问答卡';
}

function getDifficultyLabel(value?: string | null) {
  const normalized = String(value || '').trim().toLowerCase();
  return difficultyLabelMap[normalized] || value || '自由难度';
}

function normalizeCardCitations(card?: FlashcardItem | null): CitationMeta[] {
  if (!card) return [];
  const raw = Array.isArray(card.citations) ? card.citations : [];
  const fromStructured = raw
    .map((item) => {
      const sourceNumber = item?.source_number;
      if (sourceNumber === undefined || sourceNumber === null) return null;
      return {
        sourceNumber: String(sourceNumber),
        fileName: item?.file_name || undefined,
        filePath: item?.file_path || undefined,
        preview: item?.preview || card.source_excerpt || undefined,
        chunkIndex: item?.chunk_index ?? null,
      } satisfies CitationMeta;
    })
    .filter(Boolean) as CitationMeta[];
  if (fromStructured.length > 0) return fromStructured;

  const answer = String(card.answer || '');
  const numbers = Array.from(new Set([...answer.matchAll(/\[(\d+)\]/g)].map((match) => match[1])));
  return numbers.map((sourceNumber) => ({
    sourceNumber,
    fileName: card.source_file || undefined,
    preview: card.source_excerpt || undefined,
    chunkIndex: null,
  }));
}

function renderAnswerWithCitations(
  answer: string,
  citations: CitationMeta[],
  activeCitation: string | null,
  onSelectCitation: (value: string) => void,
) {
  const citationMap = new Map(citations.map((item) => [item.sourceNumber, item]));
  const parts = answer.split(/(\[\d+\])/g);
  return parts.map((part, index) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (!match) return <React.Fragment key={`text_${index}`}>{part}</React.Fragment>;
    const sourceNumber = match[1];
    const hasCitation = citationMap.has(sourceNumber);
    if (!hasCitation) return <React.Fragment key={`text_${index}`}>{part}</React.Fragment>;
    return (
      <button
        key={`cite_${sourceNumber}_${index}`}
        type="button"
        className={`thinkflow-study-inline-citation ${activeCitation === sourceNumber ? 'is-active' : ''}`}
        onClick={(event) => {
          event.stopPropagation();
          onSelectCitation(sourceNumber);
        }}
      >
        [{sourceNumber}]
      </button>
    );
  });
}

export function ThinkFlowFlashcardStudy({ cards, generationConfig, onOpenCitation }: Props) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);

  useEffect(() => {
    setCurrentIndex(0);
    setFlipped(false);
    setActiveCitation(null);
  }, [cards]);

  const currentCard = useMemo(() => cards[currentIndex] || null, [cards, currentIndex]);
  const progress = cards.length > 0 ? ((currentIndex + 1) / cards.length) * 100 : 0;
  const citations = useMemo(() => normalizeCardCitations(currentCard), [currentCard]);
  const selectedCitation = citations.find((item) => item.sourceNumber === activeCitation) || citations[0] || null;
  const canOpenFullCitation = Boolean(
    selectedCitation && onOpenCitation && (selectedCitation.filePath || selectedCitation.fileName),
  );
  const difficultyKey = String(
    currentCard?.difficulty || generationConfig?.difficulty_level || '',
  )
    .trim()
    .toLowerCase();
  const difficultyTone = difficultyToneMap[difficultyKey] || '';

  useEffect(() => {
    setActiveCitation(citations[0]?.sourceNumber || null);
  }, [currentIndex, citations]);

  if (!currentCard) return null;

  const nextCard = () => {
    if (currentIndex >= cards.length - 1) return;
    setCurrentIndex((previous) => previous + 1);
    setFlipped(false);
  };

  const previousCard = () => {
    if (currentIndex <= 0) return;
    setCurrentIndex((previous) => previous - 1);
    setFlipped(false);
  };

  return (
    <div className="thinkflow-study-shell thinkflow-study-shell-flashcard">
      <div className="thinkflow-study-head">
        <div>
          <span className="thinkflow-study-kicker">学习卡片</span>
          <h4>逐张翻卡学习当前知识点</h4>
        </div>
        <div className="thinkflow-study-progress-meta">
          <strong>
            {currentIndex + 1}/{cards.length}
          </strong>
          <span>点击卡片查看答案</span>
        </div>
      </div>

      {generationConfig ? (
        <div className="thinkflow-flashcard-config-summary">
          <div className="thinkflow-flashcard-config-head">
            <strong>本组生成条件</strong>
            {generationConfig.generated_at ? <span>{generationConfig.generated_at}</span> : null}
          </div>
          <div className="thinkflow-flashcard-config-grid">
            <span>难度：{getDifficultyLabel(generationConfig.difficulty_level)}</span>
            {generationConfig.card_count ? <span>数量：{generationConfig.card_count}</span> : null}
            {generationConfig.topic ? <span>主题：{generationConfig.topic}</span> : null}
            {generationConfig.test_focus ? <span>测试内容：{generationConfig.test_focus}</span> : null}
          </div>
        </div>
      ) : null}

      <div className="thinkflow-study-progress">
        <div className="thinkflow-study-progress-bar" style={{ width: `${progress}%` }} />
      </div>

      <button
        type="button"
        className={`thinkflow-flashcard-stage ${flipped ? 'is-flipped' : ''} ${difficultyTone}`}
        onClick={() => setFlipped((previous) => !previous)}
      >
        <div className="thinkflow-flashcard-face is-front">
          <div className="thinkflow-flashcard-face-glow" />
          <div className="thinkflow-flashcard-face-top">
            <span className="thinkflow-study-card-kicker">{getCardKindLabel(currentCard.type)}</span>
            <span className="thinkflow-study-card-chip">{getDifficultyLabel(currentCard.difficulty || generationConfig?.difficulty_level)}</span>
          </div>
          <div className="thinkflow-flashcard-front-index">#{String(currentIndex + 1).padStart(2, '0')}</div>
          <h3>{currentCard.question || '未生成问题'}</h3>
          <div className="thinkflow-flashcard-hint">
            <RotateCw size={15} />
            <span>点击翻到答案面</span>
          </div>
        </div>

        <div className="thinkflow-flashcard-face is-back">
          <div className="thinkflow-flashcard-face-glow" />
          <div className="thinkflow-flashcard-face-top">
            <span className="thinkflow-study-card-kicker">答案面</span>
            {currentCard.source_file ? <span className="thinkflow-study-card-chip">{currentCard.source_file}</span> : null}
          </div>
          <div className="thinkflow-study-card-answer">
            <span>答案</span>
            <p>{renderAnswerWithCitations(String(currentCard.answer || '未生成答案'), citations, activeCitation, setActiveCitation)}</p>
          </div>
          {selectedCitation ? (
            <div className="thinkflow-flashcard-citation-panel" onClick={(event) => event.stopPropagation()}>
              <div className="thinkflow-flashcard-citation-tabs">
                {citations.map((citation) => (
                  <button
                    key={citation.sourceNumber}
                    type="button"
                    className={`thinkflow-flashcard-citation-tab ${selectedCitation.sourceNumber === citation.sourceNumber ? 'is-active' : ''}`}
                    onClick={() => setActiveCitation(citation.sourceNumber)}
                  >
                    [{citation.sourceNumber}]
                  </button>
                ))}
              </div>
              <div className="thinkflow-flashcard-citation-card">
                <strong>{selectedCitation.fileName || `来源 [${selectedCitation.sourceNumber}]`}</strong>
                <p>{selectedCitation.preview || currentCard.source_excerpt || '暂无来源预览'}</p>
                {selectedCitation.chunkIndex !== null && selectedCitation.chunkIndex !== undefined ? (
                  <span>Chunk #{selectedCitation.chunkIndex + 1}</span>
                ) : null}
                {canOpenFullCitation && selectedCitation ? (
                  <button
                    type="button"
                    className="thinkflow-flashcard-open-source-btn"
                    onClick={() =>
                      onOpenCitation({
                        fileName: selectedCitation.fileName,
                        filePath: selectedCitation.filePath,
                        preview: selectedCitation.preview,
                        chunkIndex: selectedCitation.chunkIndex,
                        sourceNumber: selectedCitation.sourceNumber,
                      })
                    }
                  >
                    <ExternalLink size={14} />
                    打开完整来源
                  </button>
                ) : null}
              </div>
            </div>
          ) : currentCard.source_excerpt ? (
            <div className="thinkflow-study-card-quote">
              <strong>依据</strong>
              <p>{currentCard.source_excerpt}</p>
            </div>
          ) : null}
          {currentCard.tags && currentCard.tags.length > 0 ? (
            <div className="thinkflow-study-card-tags">
              {currentCard.tags.map((tag) => (
                <span key={tag} className="thinkflow-study-card-chip">
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </button>

      <div className="thinkflow-study-nav">
        <button type="button" className="thinkflow-doc-action-btn" onClick={previousCard} disabled={currentIndex === 0}>
          <ChevronLeft size={14} />
          上一张
        </button>
        <button type="button" className="thinkflow-generate-btn" onClick={nextCard} disabled={currentIndex >= cards.length - 1}>
          下一张
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

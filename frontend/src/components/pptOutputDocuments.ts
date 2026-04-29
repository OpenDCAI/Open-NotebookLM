export type PptOutputDocumentSummary = {
  id?: string;
  document_type?: string;
  metadata?: Record<string, any> | null;
};

export function findPptOutputDocumentId(
  documents: PptOutputDocumentSummary[] | null | undefined,
  outputId: string,
): string {
  const relatedOutputId = String(outputId || '').trim();
  if (!relatedOutputId) return '';

  const match = (documents || []).find((document) => {
    const metadata = document?.metadata || {};
    return (
      document?.id &&
      document.document_type === 'output_doc' &&
      metadata.output_type === 'ppt' &&
      metadata.related_output_id === relatedOutputId
    );
  });

  return match?.id || '';
}

export function resolvePptDocSlideIndex(cardIndex: number, slideCount: number): number {
  const safeSlideCount = Math.max(0, Math.floor(Number(slideCount) || 0));
  if (safeSlideCount <= 0) return 0;
  return Math.min(Math.max(0, Math.floor(Number(cardIndex) || 0)), safeSlideCount - 1);
}

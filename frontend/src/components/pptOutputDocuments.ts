export type PptOutputDocumentSummary = {
  id?: string;
  document_type?: string;
  metadata?: Record<string, any> | null;
};

export type PptOutputStageSummary = {
  id?: string;
  target_type?: string;
  pipeline_stage?: string;
  status?: string;
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

export function isPptOutputDocumentVisibleInMaterialList(
  document: PptOutputDocumentSummary,
  outputs: PptOutputStageSummary[] | null | undefined,
): boolean {
  if (document.document_type !== 'output_doc') return true;
  const metadata = document.metadata || {};
  if (metadata.output_type !== 'ppt') return true;
  const relatedOutputId = String(metadata.related_output_id || '').trim();
  if (!relatedOutputId) return true;
  const output = (outputs || []).find((item) => String(item.id || '').trim() === relatedOutputId);
  if (!output || output.target_type !== 'ppt') return false;
  const stage = String(output.pipeline_stage || output.status || '').trim();
  return stage === 'pages_ready' || stage === 'generated';
}

export function filterMaterialListDocuments<T extends PptOutputDocumentSummary>(
  documents: T[] | null | undefined,
  outputs: PptOutputStageSummary[] | null | undefined,
): T[] {
  return (documents || []).filter((document) => isPptOutputDocumentVisibleInMaterialList(document, outputs));
}

export function resolvePptDocSlideIndex(cardIndex: number, slideCount: number): number {
  const safeSlideCount = Math.max(0, Math.floor(Number(slideCount) || 0));
  if (safeSlideCount <= 0) return 0;
  return Math.min(Math.max(0, Math.floor(Number(cardIndex) || 0)), safeSlideCount - 1);
}

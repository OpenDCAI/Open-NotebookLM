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

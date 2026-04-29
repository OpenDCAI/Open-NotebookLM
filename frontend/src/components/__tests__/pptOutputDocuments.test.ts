import { describe, expect, it } from 'vitest';
import { filterMaterialListDocuments, findPptOutputDocumentId, resolvePptDocSlideIndex } from '../pptOutputDocuments';

describe('findPptOutputDocumentId', () => {
  it('finds the existing PPT output document by related output id', () => {
    const documents = [
      {
        id: 'doc_summary',
        title: '梳理摘要',
        document_type: 'summary_doc',
        metadata: {},
      },
      {
        id: 'doc_ppt',
        title: 'PPT 产出文档',
        document_type: 'output_doc',
        metadata: { output_type: 'ppt', related_output_id: 'out_1' },
      },
    ];

    expect(findPptOutputDocumentId(documents, 'out_1')).toBe('doc_ppt');
  });

  it('uses the first matching document when duplicates already exist', () => {
    const documents = [
      {
        id: 'doc_latest',
        title: 'PPT 产出文档',
        document_type: 'output_doc',
        metadata: { output_type: 'ppt', related_output_id: 'out_1' },
      },
      {
        id: 'doc_old',
        title: 'PPT 产出文档',
        document_type: 'output_doc',
        metadata: { output_type: 'ppt', related_output_id: 'out_1' },
      },
    ];

    expect(findPptOutputDocumentId(documents, 'out_1')).toBe('doc_latest');
  });

  it('ignores non-PPT output documents with the same metadata id', () => {
    const documents = [
      {
        id: 'doc_report',
        title: '报告产出文档',
        document_type: 'output_doc',
        metadata: { output_type: 'report', related_output_id: 'out_1' },
      },
    ];

    expect(findPptOutputDocumentId(documents, 'out_1')).toBe('');
  });
});

describe('resolvePptDocSlideIndex', () => {
  it('selects slides by rendered card order instead of page number text', () => {
    expect(resolvePptDocSlideIndex(2, 5)).toBe(2);
  });

  it('clamps out-of-range rendered cards to the last available slide', () => {
    expect(resolvePptDocSlideIndex(8, 3)).toBe(2);
  });
});

describe('filterMaterialListDocuments', () => {
  it('hides PPT output documents while their outline is still being discussed', () => {
    const documents = [
      {
        id: 'doc_ppt_draft',
        title: 'PPT 产出文档',
        document_type: 'output_doc',
        metadata: { output_type: 'ppt', related_output_id: 'out_draft' },
      },
      {
        id: 'doc_summary',
        title: '梳理摘要',
        document_type: 'summary_doc',
        metadata: {},
      },
    ];

    const result = filterMaterialListDocuments(documents, [
      { id: 'out_draft', target_type: 'ppt', pipeline_stage: 'outline_ready' },
    ]);

    expect(result.map((item) => item.id)).toEqual(['doc_summary']);
  });

  it('shows PPT output documents after the outline enters generation flow', () => {
    const documents = [
      {
        id: 'doc_ppt_ready',
        title: 'PPT 产出文档',
        document_type: 'output_doc',
        metadata: { output_type: 'ppt', related_output_id: 'out_ready' },
      },
    ];

    const result = filterMaterialListDocuments(documents, [
      { id: 'out_ready', target_type: 'ppt', pipeline_stage: 'pages_ready' },
    ]);

    expect(result.map((item) => item.id)).toEqual(['doc_ppt_ready']);
  });
});

import { describe, expect, it } from 'vitest';
import { getExistingOutputOpenPlan, resolveNextActiveOutputId } from '../usePptOutlineManager';

describe('resolveNextActiveOutputId', () => {
  const outputs = [
    { id: 'output_a' },
    { id: 'output_b' },
  ];

  it('does not auto-select the first output when the user is in normal chat', () => {
    expect(resolveNextActiveOutputId('', undefined, outputs)).toBe('');
  });

  it('keeps the current output when it still exists', () => {
    expect(resolveNextActiveOutputId('output_b', undefined, outputs)).toBe('output_b');
  });

  it('prefers an explicit output id when it exists', () => {
    expect(resolveNextActiveOutputId('output_a', 'output_b', outputs)).toBe('output_b');
  });

  it('clears stale output ids', () => {
    expect(resolveNextActiveOutputId('missing_output', undefined, outputs)).toBe('');
  });
});

describe('getExistingOutputOpenPlan', () => {
  it('opens a PPT outline-ready output in the dedicated chat step without loading the source document', () => {
    expect(getExistingOutputOpenPlan({
      target_type: 'ppt',
      pipeline_stage: 'outline_ready',
      status: 'outline_ready',
    })).toMatchObject({
      isPptOutlineChatStage: true,
      workspaceMode: 'normal',
      rightMode: 'doc',
      shouldEnterOutputWorkspace: false,
      shouldSyncPptOutputDocument: true,
      shouldLoadSourceDocument: false,
    });
  });

  it('opens a PPT pages-ready output in the generation workspace without loading the source document', () => {
    expect(getExistingOutputOpenPlan({
      target_type: 'ppt',
      pipeline_stage: 'pages_ready',
      status: 'pages_ready',
    })).toMatchObject({
      isPptOutlineChatStage: false,
      workspaceMode: 'output_focus',
      rightMode: 'outline',
      shouldEnterOutputWorkspace: true,
      shouldSyncPptOutputDocument: false,
      shouldLoadSourceDocument: false,
    });
  });

  it('keeps non-PPT outputs in the output workspace and may load the bound source document', () => {
    expect(getExistingOutputOpenPlan({
      target_type: 'report',
      pipeline_stage: 'outlined',
      status: 'outlined',
    })).toMatchObject({
      isPptOutput: false,
      workspaceMode: 'output_immersive',
      rightMode: 'outline',
      shouldEnterOutputWorkspace: true,
      shouldSyncPptOutputDocument: false,
      shouldLoadSourceDocument: true,
    });
  });
});

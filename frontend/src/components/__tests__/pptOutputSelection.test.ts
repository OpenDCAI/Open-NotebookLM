import { describe, expect, it } from 'vitest';
import { resolveNextActiveOutputId } from '../usePptOutlineManager';

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

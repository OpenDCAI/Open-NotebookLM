import { describe, expect, it } from 'vitest';
import { diffPptOutline } from '../pptOutlineDiff';

describe('diffPptOutline', () => {
  it('describes layout and point changes with concrete before/after details', () => {
    const diff = diffPptOutline(
      [
        {
          id: 'slide_1',
          pageNum: 1,
          title: '背景与挑战',
          layout_description: '左文右图',
          key_points: ['生产瓶颈', '运行时收益有限'],
        },
      ],
      [
        {
          id: 'slide_1',
          pageNum: 1,
          title: '背景与挑战',
          layout_description: '上方流程图，下方双栏说明',
          key_points: ['生产环境中的编码器瓶颈', '静态压缩收益更稳定'],
        },
      ],
    );

    expect(diff.totalCount).toBe(1);
    expect(diff.entries[0].detailLines).toContain('布局：左文右图 -> 上方流程图，下方双栏说明');
    expect(diff.entries[0].detailLines).toContain('移除要点：生产瓶颈、运行时收益有限');
    expect(diff.entries[0].detailLines).toContain('新增要点：生产环境中的编码器瓶颈、静态压缩收益更稳定');
  });
});

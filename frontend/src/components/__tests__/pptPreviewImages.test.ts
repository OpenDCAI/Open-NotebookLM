import { describe, expect, it } from 'vitest';
import { getPptPreviewImages } from '../usePptOutlineManager';

describe('getPptPreviewImages', () => {
  it('preserves slide positions when a page has no generated image', () => {
    const images = getPptPreviewImages({
      target_type: 'ppt',
      outline: [
        { id: 'slide_1', title: '第一页', generated_img_path: '/outputs/a/page_001.png' },
        { id: 'slide_2', title: '第二页' },
        { id: 'slide_3', title: '第三页', generated_img_path: '/outputs/a/page_003.png' },
      ],
    } as any);

    expect(images).toEqual([
      '/outputs/a/page_001.png',
      '',
      '/outputs/a/page_003.png',
    ]);
  });
});

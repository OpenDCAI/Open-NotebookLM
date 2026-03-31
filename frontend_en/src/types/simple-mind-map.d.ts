declare module 'simple-mind-map' {
  interface MindMapData {
    data: {
      text: string;
      [key: string]: any;
    };
    children?: MindMapData[];
  }

  interface MindMapOptions {
    el: HTMLElement;
    data?: MindMapData;
    theme?: string;
    layout?: string;
    scaleRatio?: number;
    minZoomRatio?: number;
    maxZoomRatio?: number;
    readonly?: boolean;
    enableFreeDrag?: boolean;
    [key: string]: any;
  }

  interface MindMapNode {
    data: { text: string; [key: string]: any };
    children?: MindMapNode[];
    nodeData: MindMapData;
    [key: string]: any;
  }

  interface MindMapView {
    enlarge(cx?: number, cy?: number): void;
    narrow(cx?: number, cy?: number): void;
    setScale(scale: number, cx?: number, cy?: number): void;
    fit(): void;
    reset(): void;
    translateXY(x: number, y: number): void;
    getTransformData(): { state: { scale: number; x: number; y: number } };
    setTransformData(data: { state: { scale: number; x: number; y: number } }): void;
  }

  class MindMap {
    constructor(options: MindMapOptions);

    static usePlugin(plugin: any): typeof MindMap;
    static defineTheme(name: string, config: Record<string, any>): void;

    view: MindMapView;

    setData(data: MindMapData): void;
    setTheme(theme: string): void;
    setThemeConfig(config: Record<string, any>): void;
    setLayout(layout: string): void;
    execCommand(command: string, ...args: any[]): void;
    export(
      type: 'png' | 'jpg' | 'svg' | 'json' | 'pdf' | 'smm' | 'md' | 'txt',
      isDownload?: boolean,
      fileName?: string,
      ...args: any[]
    ): Promise<any> | any;
    on(event: string, callback: (...args: any[]) => void): void;
    off(event: string, callback: (...args: any[]) => void): void;
    destroy(): void;
  }

  export default MindMap;
}

declare module 'simple-mind-map/src/plugins/Export.js' {
  const Export: any;
  export default Export;
}

declare module 'simple-mind-map/src/parse/markdown.js' {
  export function transformMarkdownTo(markdown: string): any;
  export function transformToMarkdown(data: any): string;
}

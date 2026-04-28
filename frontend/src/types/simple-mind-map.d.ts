declare module "simple-mind-map" {
  const MindMap: any;
  export default MindMap;
}

declare module "simple-mind-map/src/plugins/Export.js" {
  const ExportPlugin: any;
  export default ExportPlugin;
}

declare module "simple-mind-map/src/parse/markdownTo.js" {
  export function transformMarkdownTo(markdown: string): any;
}

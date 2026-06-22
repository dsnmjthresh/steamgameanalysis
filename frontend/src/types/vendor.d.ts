declare module "markdown-it" {
  interface MarkdownItOptions {
    html?: boolean;
    linkify?: boolean;
    breaks?: boolean;
  }

  class MarkdownIt {
    constructor(options?: MarkdownItOptions);
    render(source: string): string;
  }

  export default MarkdownIt;
}

declare module "echarts/core" {
  export function use(extensions: unknown[]): void;
}

declare module "echarts/renderers" {
  export const CanvasRenderer: unknown;
}

declare module "echarts/charts" {
  export const BarChart: unknown;
  export const LineChart: unknown;
}

declare module "echarts/components" {
  export const DataZoomComponent: unknown;
  export const GridComponent: unknown;
  export const LegendComponent: unknown;
  export const TooltipComponent: unknown;
  export const TitleComponent: unknown;
}

/**
 * ECharts with only the chart types and components this site uses, rendered as SVG for crisp text
 * and accessible markup. Loaded lazily by EChart when a chart is about to scroll into view, so a
 * visitor who never reaches a chart never downloads it.
 */
import { CustomChart, HeatmapChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";

echarts.use([
  HeatmapChart,
  ScatterChart,
  CustomChart,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  AriaComponent,
  SVGRenderer,
  CanvasRenderer, // the stop map: thousands of points draw faster on canvas
]);

export { echarts };

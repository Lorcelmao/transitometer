/**
 * ECharts with only the chart types and components this site uses, rendered as SVG for crisp text
 * and accessible markup. Loaded lazily by EChart when a chart is about to scroll into view, so a
 * visitor who never reaches a chart never downloads it.
 */
import { CustomChart, HeatmapChart, LinesChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  GeoComponent,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";

import { MAP_FRAME, MAP_FRAME_GEOJSON } from "@/charts/options";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";

echarts.use([
  HeatmapChart,
  ScatterChart,
  CustomChart,
  LinesChart, // the stop map's background (bus and subway route shapes)
  GeoComponent, // the stop map's zoomable, pannable longitude/latitude frame
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  AriaComponent,
  SVGRenderer,
  CanvasRenderer, // the stop map: thousands of points draw faster on canvas
]);

// The stop map's invisible frame (see MAP_FRAME): registered once, before any map is drawn.
echarts.registerMap(MAP_FRAME.name, MAP_FRAME_GEOJSON as Parameters<typeof echarts.registerMap>[1]);

export { echarts };

import { createApp } from "vue";
import { createPinia } from "pinia";
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart, LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  TitleComponent,
} from "echarts/components";
import VChart from "vue-echarts";

import App from "./App.vue";
import router from "./router";
import "./styles.css";

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  TitleComponent,
]);

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.component("VChart", VChart);
app.mount("#app");

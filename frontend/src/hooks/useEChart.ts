import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

export function useEChart(option: EChartsOption | null, deps: unknown[] = []) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const inst = echarts.init(el, undefined, { renderer: "canvas" });
    chartRef.current = inst;
    const ro = new ResizeObserver(() => inst.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      inst.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const inst = chartRef.current;
    if (!inst || !option) return;
    inst.setOption(option, { notMerge: true });
    inst.resize();
  }, [option, ...deps]);

  return elRef;
}

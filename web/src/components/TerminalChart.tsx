import { useEffect, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import { BarChart3, Crosshair, Eye, Maximize2, RotateCcw, SlidersHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import { formatPrice, labelFromCandle, type TerminalChartProps } from "./terminal-chart-support";

type ChartPoint = {
  x: number;
  y: number;
};

type DragState = {
  x: number;
  visibleEnd: number;
};

const MIN_VISIBLE_CANDLES = 36;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function isFinitePrice(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function defaultVisibleCount(timeframe: string, total: number) {
  if (total <= 0) {
    return 0;
  }
  if (timeframe === "4H") {
    return Math.min(total, 140);
  }
  if (timeframe === "15m") {
    return Math.min(total, 260);
  }
  return Math.min(total, 360);
}

function uniqueLevels<T extends { price: number; label: string }>(items: T[]) {
  const accepted: T[] = [];
  for (const item of items) {
    const duplicate = accepted.some((existing) => {
      const tolerance = Math.max(1, Math.abs(existing.price) * 0.0004);
      return existing.label === item.label && Math.abs(existing.price - item.price) <= tolerance;
    });
    if (!duplicate) {
      accepted.push(item);
    }
  }
  return accepted;
}

export function TerminalChart(props: TerminalChartProps) {
  const {
    symbol,
    candles,
    structure,
    selectedStructureFocus,
    structureFocusSource,
    onFocusStructure,
    selectedTimeframe,
    ictContext,
    status,
  } = props;
  const chartFrameRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const [chartFrame, setChartFrame] = useState({ width: 980, height: 600 });
  const [visibleCount, setVisibleCount] = useState(() => defaultVisibleCount(selectedTimeframe, candles.length));
  const [visibleEnd, setVisibleEnd] = useState(candles.length);
  const [contrast, setContrast] = useState(1.25);
  const [showVolume, setShowVolume] = useState(true);
  const [showCrosshair, setShowCrosshair] = useState(true);
  const [pointer, setPointer] = useState<ChartPoint | null>(null);

  useEffect(() => {
    const element = chartFrameRef.current;
    if (!element || typeof ResizeObserver === "undefined") {
      return;
    }

    const updateSize = (width: number, height: number) => {
      setChartFrame((current) => {
        if (current.width === width && current.height === height) {
          return current;
        }
        return { width, height };
      });
    };

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      updateSize(
        Math.max(320, Math.round(entry.contentRect.width)),
        Math.max(440, Math.round(entry.contentRect.height)),
      );
    });

    observer.observe(element);
    updateSize(Math.max(320, Math.round(element.clientWidth)), Math.max(440, Math.round(element.clientHeight)));

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    setVisibleEnd(candles.length);
    setVisibleCount(defaultVisibleCount(selectedTimeframe, candles.length));
  }, [candles.length, selectedTimeframe]);

  if (candles.length === 0) {
    return (
      <div className="terminal-panel flex h-full min-h-[360px] items-center justify-center">
        <p className="text-sm text-slate-500">Waiting for market candles...</p>
      </div>
    );
  }

  const width = chartFrame.width;
  const height = chartFrame.height;
  const leftPad = Math.max(16, Math.round(width * 0.018));
  const rightPad = Math.max(78, Math.round(width * 0.064));
  const topPad = Math.max(14, Math.round(height * 0.026));
  const bottomPad = Math.max(34, Math.round(height * 0.06));
  const volumeHeight = showVolume ? Math.max(42, Math.round(height * 0.13)) : 0;
  const volumeGap = showVolume ? 14 : 0;
  const volumeTop = height - bottomPad - volumeHeight;
  const priceBottom = showVolume ? volumeTop - volumeGap : height - bottomPad;
  const priceHeight = Math.max(180, priceBottom - topPad);
  const innerWidth = width - leftPad - rightPad;
  const minVisible = Math.min(MIN_VISIBLE_CANDLES, candles.length);
  const resolvedVisibleCount = clamp(visibleCount || defaultVisibleCount(selectedTimeframe, candles.length), minVisible, candles.length);
  const resolvedVisibleEnd = clamp(visibleEnd || candles.length, resolvedVisibleCount, candles.length);
  const visibleStart = Math.max(0, resolvedVisibleEnd - resolvedVisibleCount);
  const visibleCandles = candles.slice(visibleStart, resolvedVisibleEnd);
  const step = innerWidth / Math.max(1, visibleCandles.length);
  const bodyWidth = Math.max(1.2, Math.min(12, step * 0.66));
  const verticalGridCount = Math.max(4, Math.min(12, Math.round(innerWidth / 150)));
  const xAxisLabelStep = Math.max(1, Math.ceil(visibleCandles.length / Math.max(4, Math.floor(innerWidth / 108))));
  const latestCandle = candles[candles.length - 1];
  const latestVisibleCandle = visibleCandles[visibleCandles.length - 1] ?? latestCandle;
  const latestClose = latestCandle.close;
  const fvgFocused = selectedStructureFocus === "fvg";
  const sweepFocused = selectedStructureFocus === "sweep";
  const mssFocused = selectedStructureFocus === "mss";
  const displacementFocused = selectedStructureFocus === "displacement";
  const highContrast = contrast >= 1.35;
  const palette = {
    backgroundTop: highContrast ? "#050b12" : "#07111a",
    backgroundBottom: highContrast ? "#03070d" : "#061018",
    grid: highContrast ? "#183044" : "#10202d",
    gridSoft: highContrast ? "#0f2232" : "#0b1721",
    axis: highContrast ? "#8ea5bd" : "#63758b",
    bull: highContrast ? "#7cf5c6" : "#34d399",
    bear: highContrast ? "#ff6b81" : "#fb7185",
    current: highContrast ? "#67e8f9" : "#22d3ee",
    fvgBull: "#22d3ee",
    fvgBear: "#fb7185",
    bsl: "#fbbf24",
    ssl: "#38bdf8",
  };

  const baseMin = Math.min(...visibleCandles.map((candle) => candle.low));
  const baseMax = Math.max(...visibleCandles.map((candle) => candle.high));
  const baseRange = Math.max(1, baseMax - baseMin);
  const nearMin = baseMin - baseRange * 0.45;
  const nearMax = baseMax + baseRange * 0.45;
  const fvgLower = Number(structure?.fvg.lower ?? NaN);
  const fvgUpper = Number(structure?.fvg.upper ?? NaN);
  const fvgMidpoint = Number(structure?.fvg.midpoint ?? NaN);
  const sweepLevel = Number(structure?.sweep.level ?? NaN);
  const mssLevel = Number(structure?.mss.level ?? NaN);
  const liquidityCandidates = uniqueLevels(
    [
      isFinitePrice(structure?.drt.external_high)
        ? { label: "BSL", price: structure.drt.external_high, stroke: palette.bsl, dash: "8 6", width: 1.2 }
        : null,
      isFinitePrice(structure?.drt.range_high)
        ? { label: "BSL", price: structure.drt.range_high, stroke: palette.bsl, dash: "8 6", width: 1.2 }
        : null,
      isFinitePrice(structure?.drt.internal_high)
        ? { label: "iBSL", price: structure.drt.internal_high, stroke: palette.bsl, dash: "3 6", width: 1 }
        : null,
      isFinitePrice(structure?.drt.external_low)
        ? { label: "SSL", price: structure.drt.external_low, stroke: palette.ssl, dash: "8 6", width: 1.2 }
        : null,
      isFinitePrice(structure?.drt.range_low)
        ? { label: "SSL", price: structure.drt.range_low, stroke: palette.ssl, dash: "8 6", width: 1.2 }
        : null,
      isFinitePrice(structure?.drt.internal_low)
        ? { label: "iSSL", price: structure.drt.internal_low, stroke: palette.ssl, dash: "3 6", width: 1 }
        : null,
    ].filter((item): item is { label: string; price: number; stroke: string; dash: string; width: number } => Boolean(item)),
  ).filter((item) => item.price >= nearMin && item.price <= nearMax);
  const structuralLevels = [
    Number.isFinite(fvgLower) ? fvgLower : null,
    Number.isFinite(fvgUpper) ? fvgUpper : null,
    Number.isFinite(sweepLevel) ? sweepLevel : null,
    Number.isFinite(mssLevel) ? mssLevel : null,
    ...liquidityCandidates.map((item) => item.price),
  ].filter((value): value is number => typeof value === "number" && Number.isFinite(value));

  let minPrice = Math.min(baseMin, ...structuralLevels);
  let maxPrice = Math.max(baseMax, ...structuralLevels);
  if (minPrice === maxPrice) {
    minPrice -= 1;
    maxPrice += 1;
  }

  const priceRange = maxPrice - minPrice;
  minPrice -= priceRange * 0.08;
  maxPrice += priceRange * 0.1;
  const fullRange = maxPrice - minPrice;
  const maxVolume = Math.max(...visibleCandles.map((candle) => candle.volume), 1);
  const yForPrice = (price: number) => topPad + ((maxPrice - price) / fullRange) * priceHeight;
  const priceForY = (y: number) => maxPrice - ((y - topPad) / priceHeight) * fullRange;
  const xForVisibleIndex = (index: number) => leftPad + step * index + step / 2;

  const resolveCandlePosition = (
    timestamp: string | null | undefined,
    options: { extendBeforeVisible?: boolean } = {},
  ) => {
    if (!timestamp) {
      return null;
    }

    const targetTime = new Date(timestamp).getTime();
    if (!Number.isFinite(targetTime) || visibleCandles.length === 0) {
      return null;
    }

    const firstCandle = visibleCandles[0];
    const lastCandle = visibleCandles[visibleCandles.length - 1];
    const firstTime = new Date(firstCandle.start_at).getTime();
    const lastTime = new Date(lastCandle.start_at).getTime();
    const secondTime = visibleCandles[1] ? new Date(visibleCandles[1].start_at).getTime() : Number.NaN;
    const candleSpanMs = Number.isFinite(secondTime - firstTime) && secondTime > firstTime ? secondTime - firstTime : 0;
    const lastBoundaryTime = lastTime + Math.max(1, candleSpanMs);
    if (!Number.isFinite(firstTime) || !Number.isFinite(lastTime)) {
      return null;
    }

    if (targetTime < firstTime) {
      if (!options.extendBeforeVisible) {
        return null;
      }
      return {
        index: 0,
        x: leftPad,
        candle: firstCandle,
      };
    }

    if (targetTime > lastBoundaryTime) {
      return null;
    }

    let closestIndex = -1;
    let smallestDelta = Number.POSITIVE_INFINITY;
    visibleCandles.forEach((candle, index) => {
      const candleTime = new Date(candle.start_at).getTime();
      const delta = Math.abs(candleTime - targetTime);
      if (delta < smallestDelta) {
        smallestDelta = delta;
        closestIndex = index;
      }
    });

    if (closestIndex < 0) {
      return null;
    }

    return {
      index: closestIndex,
      x: xForVisibleIndex(closestIndex),
      candle: visibleCandles[closestIndex],
    };
  };

  const fitDefault = () => {
    setVisibleEnd(candles.length);
    setVisibleCount(defaultVisibleCount(selectedTimeframe, candles.length));
  };

  const fitAll = () => {
    setVisibleEnd(candles.length);
    setVisibleCount(candles.length);
  };

  const updateZoom = (factor: number) => {
    const nextCount = clamp(Math.round(resolvedVisibleCount * factor), minVisible, candles.length);
    setVisibleCount(nextCount);
    setVisibleEnd((current) => clamp(current || candles.length, nextCount, candles.length));
  };

  const panByCandles = (delta: number) => {
    setVisibleEnd((current) => clamp((current || resolvedVisibleEnd) + delta, resolvedVisibleCount, candles.length));
  };

  const handleWheel = (event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      panByCandles(Math.round(event.deltaX / Math.max(12, step * 3)));
      return;
    }
    updateZoom(event.deltaY > 0 ? 1.16 : 0.86);
  };

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    dragRef.current = { x: event.clientX, visibleEnd: resolvedVisibleEnd };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const nextPointer = {
      x: clamp(event.clientX - rect.left, leftPad, width - rightPad),
      y: clamp(event.clientY - rect.top, topPad, priceBottom),
    };
    setPointer(nextPointer);

    if (!dragRef.current) {
      return;
    }

    const candleDelta = Math.round((event.clientX - dragRef.current.x) / Math.max(1, step));
    setVisibleEnd(clamp(dragRef.current.visibleEnd - candleDelta, resolvedVisibleCount, candles.length));
  };

  const handlePointerEnd = (event: PointerEvent<SVGSVGElement>) => {
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const priceScale = Array.from({ length: 6 }).map((_, index) => {
    const ratio = index / 5;
    const value = maxPrice - fullRange * ratio;
    return {
      value,
      y: topPad + priceHeight * ratio,
    };
  });
  const fvgPosition = resolveCandlePosition(structure?.fvg.at, { extendBeforeVisible: true });
  const displacementPosition = resolveCandlePosition(structure?.displacement.at);
  const mssPosition = resolveCandlePosition(structure?.mss.broken_swing_at ?? structure?.mss.at, { extendBeforeVisible: true });
  const fvgActive = structure?.fvg.state !== "none" && Number.isFinite(fvgLower) && Number.isFinite(fvgUpper) && Boolean(fvgPosition);
  const sweepActive = structure?.sweep.state !== "none" && Number.isFinite(sweepLevel);
  const mssActive = structure?.mss.state !== "none" && Number.isFinite(mssLevel) && Boolean(mssPosition);
  const displacementActive = structure?.displacement.state !== "none" && displacementPosition;
  const fvgTone = structure?.fvg.state === "bullish" ? palette.fvgBull : palette.fvgBear;
  const mssTone = structure?.mss.state === "bullish_mss" ? palette.bull : palette.bear;
  const displacementTone = structure?.displacement.state === "bullish" ? palette.bull : palette.bear;
  const crosshairCandleIndex = pointer
    ? clamp(Math.floor((pointer.x - leftPad) / Math.max(1, step)), 0, visibleCandles.length - 1)
    : -1;
  const crosshairCandle = crosshairCandleIndex >= 0 ? visibleCandles[crosshairCandleIndex] : null;
  const crosshairX = crosshairCandleIndex >= 0 ? xForVisibleIndex(crosshairCandleIndex) : pointer?.x ?? 0;
  const crosshairPrice = pointer ? priceForY(pointer.y) : null;
  const currentPriceY = yForPrice(latestClose);
  const visibleRangeLabel = `${visibleCandles.length}/${candles.length}`;
  const structureSourceLabel = structureFocusSource === "event" ? "event" : selectedStructureFocus ? "lens" : "auto";
  const fvgStartX = fvgPosition ? Math.max(leftPad, fvgPosition.x - step) : leftPad;
  const fvgLabelX = fvgPosition ? fvgPosition.x : leftPad + 10;
  const mssStartX = mssPosition ? Math.max(leftPad, mssPosition.x - step * 0.5) : leftPad;

  const toolButtonClass =
    "inline-flex h-8 w-8 items-center justify-center rounded border border-slate-800 bg-[#071019] text-slate-300 transition hover:border-cyan-400/30 hover:text-cyan-200";
  const activeToolButtonClass = "border-cyan-400/35 bg-cyan-400/10 text-cyan-200";

  return (
    <div className="terminal-panel flex h-full min-h-0 flex-col p-2">
      <div className="mb-2 flex shrink-0 flex-wrap items-center justify-between gap-2 rounded border border-slate-800 bg-[#071019] px-3 py-2">
        <div className="flex min-w-0 items-center gap-3">
          <span className="font-mono text-sm font-semibold text-slate-100">{symbol}</span>
          <span className="rounded border border-slate-800 px-2 py-1 font-mono text-[11px] uppercase tracking-[0.14em] text-cyan-300">
            {selectedTimeframe}
          </span>
          <span className="hidden truncate font-mono text-[11px] uppercase tracking-[0.14em] text-slate-500 sm:inline">
            {ictContext.biasTimeframe}/{ictContext.setupTimeframe}/{ictContext.executionTimeframe} · {structureSourceLabel} · {visibleRangeLabel}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button type="button" className={toolButtonClass} title="Zoom in" aria-label="Zoom in" onClick={() => updateZoom(0.78)}>
            <ZoomIn size={15} strokeWidth={1.8} />
          </button>
          <button type="button" className={toolButtonClass} title="Zoom out" aria-label="Zoom out" onClick={() => updateZoom(1.28)}>
            <ZoomOut size={15} strokeWidth={1.8} />
          </button>
          <button type="button" className={toolButtonClass} title="Fit all" aria-label="Fit all" onClick={fitAll}>
            <Maximize2 size={15} strokeWidth={1.8} />
          </button>
          <button type="button" className={toolButtonClass} title="Reset view" aria-label="Reset view" onClick={fitDefault}>
            <RotateCcw size={15} strokeWidth={1.8} />
          </button>
          <button
            type="button"
            className={`${toolButtonClass} ${showCrosshair ? activeToolButtonClass : ""}`}
            title="Crosshair"
            aria-label="Crosshair"
            onClick={() => setShowCrosshair((current) => !current)}
          >
            <Crosshair size={15} strokeWidth={1.8} />
          </button>
          <button
            type="button"
            className={`${toolButtonClass} ${showVolume ? activeToolButtonClass : ""}`}
            title="Volume"
            aria-label="Volume"
            onClick={() => setShowVolume((current) => !current)}
          >
            <BarChart3 size={15} strokeWidth={1.8} />
          </button>
          <label className="ml-1 hidden items-center gap-2 rounded border border-slate-800 bg-[#071019] px-2 py-1.5 text-slate-400 sm:inline-flex">
            <SlidersHorizontal size={14} strokeWidth={1.8} />
            <input
              aria-label="Contrast"
              title="Contrast"
              type="range"
              min="0.8"
              max="1.8"
              step="0.05"
              value={contrast}
              onChange={(event) => setContrast(Number(event.target.value))}
              className="h-1.5 w-20 accent-cyan-300"
            />
          </label>
          <button type="button" className={toolButtonClass} title="Latest candles" aria-label="Latest candles" onClick={() => setVisibleEnd(candles.length)}>
            <Eye size={15} strokeWidth={1.8} />
          </button>
        </div>
      </div>

      <div ref={chartFrameRef} className="min-h-[440px] flex-1 cursor-grab active:cursor-grabbing">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-full w-full rounded"
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
          onPointerLeave={() => {
            setPointer(null);
            dragRef.current = null;
          }}
        >
          <defs>
            <linearGradient id="chartBackdrop" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={palette.backgroundTop} />
              <stop offset="100%" stopColor={palette.backgroundBottom} />
            </linearGradient>
          </defs>

          <rect x="0" y="0" width={width} height={height} rx="6" fill="url(#chartBackdrop)" />

          <rect x={leftPad} y={topPad} width={innerWidth} height={priceHeight} fill="#020617" opacity={highContrast ? "0.26" : "0.18"} />

          {priceScale.map((level, index) => (
            <g key={index}>
              <line x1={leftPad} x2={width - rightPad} y1={level.y} y2={level.y} stroke={palette.grid} strokeWidth="1" />
              <text x={width - rightPad + 10} y={level.y + 4} fill={palette.axis} fontSize="11">
                {formatPrice(level.value)}
              </text>
            </g>
          ))}

          {Array.from({ length: verticalGridCount }).map((_, index) => {
            const denominator = Math.max(1, verticalGridCount - 1);
            const x = leftPad + (innerWidth / denominator) * index;
            return <line key={`v-${index}`} x1={x} x2={x} y1={topPad} y2={priceBottom} stroke={palette.gridSoft} strokeWidth="1" />;
          })}

          {liquidityCandidates.map((line) => {
            const y = yForPrice(line.price);
            return (
              <g key={`${line.label}-${line.price}`}>
                <line
                  x1={leftPad}
                  x2={width - rightPad}
                  y1={y}
                  y2={y}
                  stroke={line.stroke}
                  strokeDasharray={line.dash}
                  strokeOpacity={line.label.startsWith("i") ? "0.52" : "0.78"}
                  strokeWidth={line.width}
                />
                <rect x={leftPad + 8} y={y - 10} width={line.label.startsWith("i") ? 46 : 42} height="18" rx="4" fill="#061018" stroke={line.stroke} />
                <text x={leftPad + (line.label.startsWith("i") ? 31 : 29)} y={y + 2.5} fill={line.stroke} fontSize="10" fontWeight="700" textAnchor="middle">
                  {line.label}
                </text>
              </g>
            );
          })}

          {fvgActive ? (
            <g className="cursor-pointer" onClick={() => onFocusStructure("fvg")}>
              <rect
                x={fvgStartX}
                y={Math.min(yForPrice(fvgUpper), yForPrice(fvgLower))}
                width={width - rightPad - fvgStartX}
                height={Math.max(2, Math.abs(yForPrice(fvgUpper) - yForPrice(fvgLower)))}
                fill={fvgTone}
                opacity={fvgFocused ? "0.18" : "0.1"}
                stroke={fvgFocused ? fvgTone : "none"}
                strokeWidth={fvgFocused ? "1.4" : "0"}
              />
              {Number.isFinite(fvgMidpoint) ? (
                <line
                  x1={fvgStartX}
                  x2={width - rightPad}
                  y1={yForPrice(fvgMidpoint)}
                  y2={yForPrice(fvgMidpoint)}
                  stroke={fvgTone}
                  strokeDasharray="5 6"
                  strokeOpacity={fvgFocused ? "0.95" : "0.62"}
                />
              ) : null}
              <rect
                x={Math.min(width - rightPad - 46, Math.max(leftPad + 10, fvgLabelX))}
                y={Math.min(yForPrice(fvgUpper), yForPrice(fvgLower)) - 22}
                width="42"
                height="18"
                rx="4"
                fill="#061018"
                stroke={fvgTone}
              />
              <text
                x={Math.min(width - rightPad - 25, Math.max(leftPad + 31, fvgLabelX + 21))}
                y={Math.min(yForPrice(fvgUpper), yForPrice(fvgLower)) - 9}
                fill={fvgTone}
                fontSize="10"
                fontWeight="700"
                textAnchor="middle"
              >
                FVG
              </text>
            </g>
          ) : null}

          {displacementActive ? (
            <g className="cursor-pointer" onClick={() => onFocusStructure("displacement")}>
              <rect
                x={Math.max(leftPad, displacementPosition.x - (structure?.displacement.mode === "sequence" ? step * 1.1 : step * 0.65))}
                y={topPad}
                width={structure?.displacement.mode === "sequence" ? step * 2.2 : step * 1.3}
                height={priceHeight}
                fill={displacementTone}
                opacity={displacementFocused ? "0.12" : "0.065"}
                stroke={displacementFocused ? displacementTone : "none"}
                strokeWidth={displacementFocused ? "1.2" : "0"}
              />
              <text x={displacementPosition.x} y={topPad + 18} fill={displacementTone} fontSize="10" fontWeight="700" textAnchor="middle">
                DISP
              </text>
            </g>
          ) : null}

          {sweepActive ? (
            <g className="cursor-pointer" onClick={() => onFocusStructure("sweep")}>
              <line
                x1={leftPad}
                x2={width - rightPad}
                y1={yForPrice(sweepLevel)}
                y2={yForPrice(sweepLevel)}
                stroke={palette.bsl}
                strokeOpacity={sweepFocused ? "0.9" : "0.66"}
                strokeDasharray="8 6"
                strokeWidth={sweepFocused ? "1.8" : "1.1"}
              />
              <rect x={leftPad + 58} y={yForPrice(sweepLevel) - 10} width="72" height="18" rx="4" fill="#061018" stroke={palette.bsl} />
              <text x={leftPad + 94} y={yForPrice(sweepLevel) + 2.5} fill="#fcd34d" fontSize="10" fontWeight="700" textAnchor="middle">
                SWEEP
              </text>
            </g>
          ) : null}

          {mssActive ? (
            <g className="cursor-pointer" onClick={() => onFocusStructure("mss")}>
              <line
                x1={mssStartX}
                x2={width - rightPad}
                y1={yForPrice(mssLevel)}
                y2={yForPrice(mssLevel)}
                stroke={mssTone}
                strokeOpacity={mssFocused ? "0.95" : "0.7"}
                strokeDasharray="4 5"
                strokeWidth={mssFocused ? "1.9" : "1.2"}
              />
              <rect x={leftPad + 136} y={yForPrice(mssLevel) - 10} width="58" height="18" rx="4" fill="#061018" stroke={mssTone} />
              <text x={leftPad + 165} y={yForPrice(mssLevel) + 2.5} fill={mssTone} fontSize="10" fontWeight="700" textAnchor="middle">
                MSS
              </text>
            </g>
          ) : null}

          {visibleCandles.map((candle, index) => {
            const centerX = xForVisibleIndex(index);
            const wickTop = yForPrice(candle.high);
            const wickBottom = yForPrice(candle.low);
            const openY = yForPrice(candle.open);
            const closeY = yForPrice(candle.close);
            const bodyY = Math.min(openY, closeY);
            const bodyHeight = Math.max(1.6, Math.abs(closeY - openY));
            const bullish = candle.close >= candle.open;
            const bodyColor = bullish ? palette.bull : palette.bear;
            const volumeHeightScaled = showVolume ? (candle.volume / maxVolume) * volumeHeight : 0;
            const volumeY = volumeTop + (volumeHeight - volumeHeightScaled);

            return (
              <g key={candle.start_ms}>
                <line x1={centerX} x2={centerX} y1={wickTop} y2={wickBottom} stroke={bodyColor} strokeWidth={step < 3 ? "1" : "1.35"} />
                <rect x={centerX - bodyWidth / 2} y={bodyY} width={bodyWidth} height={bodyHeight} fill={bodyColor} rx={step < 3 ? "0.6" : "1.3"} />
                {showVolume ? (
                  <rect
                    x={centerX - bodyWidth / 2}
                    y={volumeY}
                    width={bodyWidth}
                    height={Math.max(1.2, volumeHeightScaled)}
                    fill={bullish ? palette.bull : palette.bear}
                    opacity={highContrast ? "0.58" : "0.42"}
                    rx="0.8"
                  />
                ) : null}
              </g>
            );
          })}

          <line
            x1={leftPad}
            x2={width - rightPad}
            y1={currentPriceY}
            y2={currentPriceY}
            stroke={palette.current}
            strokeOpacity="0.82"
            strokeWidth="1.2"
            strokeDasharray="4 5"
          />
          <rect x={width - rightPad + 8} y={currentPriceY - 11} width="66" height="22" rx="5" fill="#061018" stroke={palette.current} />
          <text x={width - rightPad + 41} y={currentPriceY + 3.5} fill={palette.current} fontSize="11" fontWeight="700" textAnchor="middle">
            {formatPrice(latestClose)}
          </text>

          {showCrosshair && pointer && crosshairCandle && crosshairPrice !== null ? (
            <g pointerEvents="none">
              <line x1={crosshairX} x2={crosshairX} y1={topPad} y2={priceBottom} stroke="#94a3b8" strokeOpacity="0.36" strokeDasharray="3 5" />
              <line x1={leftPad} x2={width - rightPad} y1={pointer.y} y2={pointer.y} stroke="#94a3b8" strokeOpacity="0.28" strokeDasharray="3 5" />
              <rect x={width - rightPad + 8} y={pointer.y - 10} width="66" height="20" rx="4" fill="#061018" stroke="#64748b" />
              <text x={width - rightPad + 41} y={pointer.y + 3} fill="#cbd5e1" fontSize="10.5" fontWeight="700" textAnchor="middle">
                {formatPrice(crosshairPrice)}
              </text>
              <rect x={Math.max(leftPad, crosshairX - 44)} y={height - bottomPad + 4} width="88" height="20" rx="4" fill="#061018" stroke="#64748b" />
              <text x={Math.max(leftPad + 44, crosshairX)} y={height - bottomPad + 18} fill="#cbd5e1" fontSize="10.5" fontWeight="700" textAnchor="middle">
                {labelFromCandle(crosshairCandle)}
              </text>
            </g>
          ) : null}

          {visibleCandles
            .filter((_, index) => index % xAxisLabelStep === 0 || index === visibleCandles.length - 1)
            .map((candle, index) => {
              const candleIndex = visibleCandles.findIndex((item) => item.start_ms === candle.start_ms);
              const x = xForVisibleIndex(candleIndex);
              return (
                <text key={`label-${index}`} x={x - 18} y={height - bottomPad / 2} fill={palette.axis} fontSize="11">
                  {labelFromCandle(candle)}
                </text>
              );
            })}

          <text x={leftPad} y={topPad + 14} fill="#94a3b8" fontSize="10.5" fontWeight="700" letterSpacing="1.4">
            {status.signal} · {status.session} · {latestVisibleCandle ? formatPrice(latestVisibleCandle.close) : "-"}
          </text>
        </svg>
      </div>
    </div>
  );
}

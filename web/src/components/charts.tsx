/* Hand-built SVG charts in the teal system: soft area fills, dashed grid,
   direct value labels, no legends. */
import { toNum } from "../format";

export interface Point { x: string; y: number | null; inferred?: boolean }

function Defs() {
  return (
    <defs>
      <linearGradient id="tealfade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#0e7c6b" stopOpacity="0.18" />
        <stop offset="100%" stopColor="#0e7c6b" stopOpacity="0" />
      </linearGradient>
    </defs>
  );
}

/** Growth per year between first and last point, as a percentage. */
export function cagr(points: Point[]): number | null {
  const pts = points.filter((p) => p.y !== null && !p.inferred) as (Point & { y: number })[];
  if (pts.length < 2) return null;
  const a = pts[0], b = pts[pts.length - 1];
  const yrs = (new Date(b.x).getTime() - new Date(a.x).getTime()) / (365.25 * 864e5);
  if (yrs < 0.8 || a.y <= 0 || b.y <= 0) return null;
  return (Math.pow(b.y / a.y, 1 / yrs) - 1) * 100;
}

export function AreaChart({
  title, points, format, height = 120,
}: { title: string; points: Point[]; format: (n: number) => string; height?: number }) {
  const pts = points.filter((p) => p.y !== null) as (Point & { y: number })[];
  const w = 260, padL = 4, padR = 8, padT = 10, padB = 20;
  const g = cagr(points);
  const last = pts[pts.length - 1];
  return (
    <div>
      <h3>
        <span>{title}</span>
        {g !== null && <span className={`delta ${g < 0 ? "down" : ""}`}>{g >= 0 ? "+" : ""}{g.toFixed(0)}% a year</span>}
      </h3>
      {pts.length === 0 ? (
        <div className="faint small" style={{ height: height + 28, display: "grid", placeItems: "center" }}>Not filed</div>
      ) : (
        <>
          <div className="big">{format(last.y)}</div>
          {(() => {
            const ys = pts.map((p) => p.y);
            let lo = Math.min(...ys, 0), hi = Math.max(...ys, 0);
            if (lo === hi) hi = lo + 1;
            hi += (hi - lo) * 0.08;
            const X = (i: number) => padL + (pts.length === 1 ? (w - padL - padR) / 2 : (i * (w - padL - padR)) / (pts.length - 1));
            const Y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * (height - padT - padB);
            const line = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ");
            const area = `${line} L${X(pts.length - 1).toFixed(1)},${Y(Math.max(lo, 0))} L${X(0).toFixed(1)},${Y(Math.max(lo, 0))} Z`;
            return (
              <svg className="chart" width="100%" viewBox={`0 0 ${w} ${height}`} role="img" aria-label={`${title} by year`}>
                <Defs />
                {[0.33, 0.66].map((f) => <line key={f} className="grid" x1={0} x2={w} y1={padT + f * (height - padT - padB)} y2={padT + f * (height - padT - padB)} />)}
                {lo < 0 && <line className="zero" x1={0} x2={w} y1={Y(0)} y2={Y(0)} />}
                {pts.length > 1 && <path className="area" d={area} />}
                {pts.length > 1 && <path className="line" d={line} />}
                {pts.map((p, i) => (
                  <circle key={p.x} className={`dot ${p.inferred ? "inferred" : ""}`} cx={X(i)} cy={Y(p.y)} r={3.2}>
                    <title>{`${p.x.slice(0, 10)}: ${format(p.y)}${p.inferred ? " (prior year, date inferred)" : ""}`}</title>
                  </circle>
                ))}
                {pts.map((p, i) => (pts.length <= 6 || i % Math.ceil(pts.length / 6) === 0 || i === pts.length - 1) && (
                  <text key={`t${p.x}`} x={X(i)} y={height - 4} textAnchor={i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}>
                    {p.x.slice(0, 4)}
                  </text>
                ))}
              </svg>
            );
          })()}
        </>
      )}
    </div>
  );
}

// Kept for compatibility with older imports.
export const SmallLine = AreaChart;

export function Spark({ values, w = 64, h = 20 }: { values: (number | null)[] | null | undefined; w?: number; h?: number }) {
  const v = (values ?? []).filter((x): x is number => x !== null);
  if (v.length < 2) return null;
  const lo = Math.min(...v), hi = Math.max(...v) === lo ? lo + 1 : Math.max(...v);
  const X = (i: number) => 1 + (i * (w - 2)) / (v.length - 1);
  const Y = (x: number) => h - 2 - ((x - lo) / (hi - lo)) * (h - 4);
  const up = v[v.length - 1] >= v[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden style={{ display: "block", flex: "none" }}>
      <path d={v.map((x, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(x).toFixed(1)}`).join(" ")}
            fill="none" stroke={up ? "#0e7c6b" : "#c8352b"} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={X(v.length - 1)} cy={Y(v[v.length - 1])} r="2" fill={up ? "#0e7c6b" : "#c8352b"} />
    </svg>
  );
}

export function HBars({
  rows, accent, onPick,
}: { rows: { label: string; n: number | string; key?: string }[]; accent?: (key: string) => boolean; onPick?: (key: string) => void }) {
  const max = Math.max(1, ...rows.map((r) => toNum(r.n) ?? 0));
  return (
    <table className="hbars">
      <tbody>
        {rows.map((r) => {
          const n = toNum(r.n) ?? 0;
          const key = r.key ?? r.label;
          return (
            <tr key={key} className={accent?.(key) ? "accent" : ""} style={onPick ? { cursor: "pointer" } : undefined}
                onClick={onPick ? () => onPick(key) : undefined}>
              <td className="lab">{r.label}</td>
              <td className="track"><span><i style={{ width: `${(100 * n) / max}%` }} /></span></td>
              <td className="n">{n.toLocaleString("en-GB")}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function Columns({ rows, height = 150, highlight }: { rows: { label: string; n: number }[]; height?: number; highlight?: (i: number) => boolean }) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  const w = 400, gap = 6, padB = 20, padT = 18;
  const bw = (w - gap * (rows.length - 1)) / Math.max(rows.length, 1);
  return (
    <svg className="chart" width="100%" viewBox={`0 0 ${w} ${height}`} role="img">
      {[0.5].map((f) => <line key={f} className="grid" x1={0} x2={w} y1={padT + f * (height - padT - padB)} y2={padT + f * (height - padT - padB)} />)}
      {rows.map((r, i) => {
        const h = ((height - padB - padT) * r.n) / max;
        const x = i * (bw + gap);
        const y = height - padB - Math.max(h, r.n ? 2 : 0);
        return (
          <g key={r.label}>
            <rect className={`bar ${highlight && !highlight(i) ? "muted" : ""}`} x={x} y={y} width={bw} height={Math.max(h, r.n ? 2 : 0)} rx={4}>
              <title>{`${r.label}: ${r.n}`}</title>
            </rect>
            {r.n > 0 && <text className="value" x={x + bw / 2} y={y - 5} textAnchor="middle">{r.n}</text>}
            <text x={x + bw / 2} y={height - 5} textAnchor="middle">{r.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function TrendLine({ points, format, height = 170 }: { points: { x: string; y: number }[]; format: (n: number) => string; height?: number }) {
  if (points.length < 2) return <div className="faint small" style={{ padding: "30px 0" }}>Needs at least two years of filed accounts. Load accounts data on the Data page.</div>;
  const w = 600, padL = 36, padR = 12, padT = 14, padB = 22;
  const ys = points.map((p) => p.y);
  const lo = 0, hi = Math.max(...ys) * 1.15 || 1;
  const X = (i: number) => padL + (i * (w - padL - padR)) / (points.length - 1);
  const Y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * (height - padT - padB);
  const line = points.map((p, i) => `${i ? "L" : "M"}${X(i)},${Y(p.y)}`).join(" ");
  const area = `${line} L${X(points.length - 1)},${Y(0)} L${X(0)},${Y(0)} Z`;
  return (
    <svg className="chart" width="100%" viewBox={`0 0 ${w} ${height}`} role="img">
      <Defs />
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line className="grid" x1={padL} x2={w - padR} y1={Y(hi * f / 1.15)} y2={Y(hi * f / 1.15)} />
          <text x={padL - 6} y={Y(hi * f / 1.15) + 4} textAnchor="end">{format(hi * f / 1.15)}</text>
        </g>
      ))}
      <path className="area" d={area} />
      <path className="line" d={line} />
      {points.map((p, i) => (
        <g key={p.x}>
          <circle className="dot" cx={X(i)} cy={Y(p.y)} r={3.5}><title>{`${p.x}: ${format(p.y)}`}</title></circle>
          <text x={X(i)} y={height - 5} textAnchor="middle">{p.x}</text>
        </g>
      ))}
    </svg>
  );
}

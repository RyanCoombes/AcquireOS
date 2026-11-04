/* Hand-drawn SVG charts. Thin lines, direct labels, no legends. */
import { toNum } from "../format";

export interface Point { x: string; y: number | null; inferred?: boolean }

export function SmallLine({
  title, points, format, height = 92,
}: { title: string; points: Point[]; format: (n: number) => string; height?: number }) {
  const pts = points.filter((p) => p.y !== null) as (Point & { y: number })[];
  const w = 220, padL = 2, padR = 54, padT = 14, padB = 18;
  const last = pts[pts.length - 1];
  const first = pts[0];
  return (
    <div>
      <h3>{title}</h3>
      {pts.length === 0 ? (
        <div className="faint small" style={{ height }}>Not filed</div>
      ) : (
        (() => {
          const ys = pts.map((p) => p.y);
          let lo = Math.min(...ys, 0), hi = Math.max(...ys, 0);
          if (lo === hi) { hi = lo + 1; }
          const X = (i: number) => padL + (pts.length === 1 ? (w - padL - padR) / 2 : (i * (w - padL - padR)) / (pts.length - 1));
          const Y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * (height - padT - padB);
          const d = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ");
          const change = first && last && pts.length > 1 ? last.y - first.y : null;
          return (
            <svg className="chart" width="100%" viewBox={`0 0 ${w} ${height}`} role="img" aria-label={title}>
              {lo < 0 && <line className="zero" x1={0} x2={w - padR} y1={Y(0)} y2={Y(0)} />}
              <path className="line" d={d} />
              {pts.map((p, i) => (
                <circle key={p.x} className={`dot ${p.inferred ? "inferred" : ""}`} cx={X(i)} cy={Y(p.y)} r={2.6}>
                  <title>{`${p.x}: ${format(p.y)}${p.inferred ? " (prior year, date inferred)" : ""}`}</title>
                </circle>
              ))}
              <text className="value" x={X(pts.length - 1) + 7} y={Y(last.y) + 4}>{format(last.y)}</text>
              {change !== null && (
                <text x={X(pts.length - 1) + 7} y={Y(last.y) + 18} style={{ fill: change < 0 ? "var(--red)" : "var(--green)" }}>
                  {change >= 0 ? "+" : "−"}{format(Math.abs(change)).replace("−", "")}
                </text>
              )}
              <text x={padL} y={height - 3}>{first.x.slice(0, 4)}</text>
              {pts.length > 1 && <text x={X(pts.length - 1)} y={height - 3} textAnchor="end">{last.x.slice(0, 4)}</text>}
            </svg>
          );
        })()
      )}
    </div>
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
              <td className="track"><i style={{ width: `${(100 * n) / max}%` }} /></td>
              <td className="n num">{n.toLocaleString("en-GB")}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function Columns({ rows, height = 120 }: { rows: { label: string; n: number }[]; height?: number }) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  const w = 360, gap = 4, padB = 18, padT = 16;
  const bw = (w - gap * (rows.length - 1)) / Math.max(rows.length, 1);
  return (
    <svg className="chart" width="100%" viewBox={`0 0 ${w} ${height}`} role="img">
      {rows.map((r, i) => {
        const h = ((height - padB - padT) * r.n) / max;
        const x = i * (bw + gap);
        return (
          <g key={r.label}>
            <rect x={x} y={height - padB - h} width={bw} height={Math.max(h, r.n ? 1 : 0)} fill="var(--ink)">
              <title>{`${r.label}: ${r.n}`}</title>
            </rect>
            {r.n > 0 && <text className="value" x={x + bw / 2} y={height - padB - h - 4} textAnchor="middle">{r.n}</text>}
            <text x={x + bw / 2} y={height - 4} textAnchor="middle">{r.label}</text>
          </g>
        );
      })}
      <line x1={0} x2={w} y1={height - padB} y2={height - padB} stroke="var(--ink)" />
    </svg>
  );
}

import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import { Columns, HBars } from "../components/charts";
import { dateTime, FLAGS, OWNERSHIP } from "../format";

export default function Reports() {
  const nav = useNavigate();
  const { data, error } = useAsync(() => api.reports(), []);
  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const hist = Array.from({ length: 10 }, (_, i) => ({
    label: `${i * 10}`,
    n: Number(data.score_hist.find((h: any) => h.bucket === i + 1 || (i === 9 && h.bucket === 11))?.n ?? 0),
  }));

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Reports</h1>
          <div className="lede">The shape of your dataset and your search. Click a bar to see those companies.</div>
        </div>
      </div>
      <div className="report-grid">
        <section>
          <h2>Search funnel</h2>
          <HBars rows={data.funnel.map((f: any) => ({ label: f.label, n: f.n, key: f.status }))}
                 accent={(k) => k === "in_talks"} onPick={(k) => nav(`/targets?status=${k}&include_excluded=1`)} />
        </section>
        <section>
          <h2>Score spread</h2>
          <p className="muted small" style={{ marginTop: -4 }}>Companies in scope, by score band (0–9, 10–19 …).</p>
          <Columns rows={hist} />
        </section>
        <section>
          <h2>Staff size</h2>
          <HBars rows={data.staff.map((s: any) => ({ label: s.band, n: s.n }))} accent={(k) => ["20–49", "50–99"].includes(k)} />
        </section>
        <section>
          <h2>Ownership</h2>
          <HBars rows={data.ownership.map((o: any) => ({ label: OWNERSHIP[o.type] ?? o.type, n: o.n, key: o.type }))}
                 accent={(k) => k === "owner_held"} onPick={(k) => nav(`/targets?ownership=${k}&include_excluded=1`)} />
        </section>
        <section>
          <h2>Oldest owner's age</h2>
          {data.owner_age.length ? (
            <Columns rows={data.owner_age.map((a: any) => ({ label: `${a.age}`, n: Number(a.n) }))} />
          ) : <div className="faint">No owner ages yet. Import the PSC snapshot.</div>}
        </section>
        <section>
          <h2>Why companies were excluded</h2>
          {data.exclusions.length ? <HBars rows={data.exclusions.map((e: any) => ({ label: e.reason, n: e.n }))} /> : <div className="faint">Nothing excluded.</div>}
        </section>
        <section>
          <h2>Regions</h2>
          <HBars rows={data.regions.map((r: any) => ({ label: r.region, n: r.n }))} onPick={(k) => k !== "Not set" && nav(`/targets?region=${encodeURIComponent(k)}`)} />
        </section>
        <section>
          <h2>Review tiers</h2>
          <HBars rows={data.tiers.map((t: any) => ({ label: t.tier, n: t.n }))} onPick={(k) => k !== "Not set" && nav(`/targets?tier=${encodeURIComponent(k)}&include_excluded=1`)} />
        </section>
        <section>
          <h2>Flags</h2>
          {[...data.flags, ...data.address_flags].length ? (
            <HBars rows={[...data.flags, ...data.address_flags].map((f: any) => ({ label: FLAGS[f.flag] ?? f.flag, n: f.n, key: f.flag }))}
                   onPick={(k) => nav(`/targets?flag=${k}&include_excluded=1`)} />
          ) : <div className="faint">No flags raised.</div>}
        </section>
        <section>
          <h2>Recent imports</h2>
          {data.imports.length ? (
            <table>
              <tbody>
                {data.imports.map((i: any) => (
                  <tr key={i.id}>
                    <td>{i.filename}<div className="sub">{i.kind} · {dateTime(i.finished_at ?? i.started_at)}</div></td>
                    <td className="num">{i.rows_ok.toLocaleString("en-GB")} rows</td>
                    <td className="num faint">{i.rows_skipped ? `${i.rows_skipped} skipped` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="faint">No imports yet. <Link to="/import">Import data</Link>.</div>}
        </section>
      </div>
    </>
  );
}

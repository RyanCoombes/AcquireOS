/* Your own criteria, scored 0-5. Scores belong to the company, so they count
   in every buy box that uses the same criterion. */
import { useEffect, useState } from "react";
import { api, type ManualCriterion, type ManualValue } from "../api";

export default function MyScores({
  num, criteria, values, onChange, focus, compact,
}: {
  num: string; criteria: ManualCriterion[]; values: Record<string, ManualValue>;
  onChange?: (values: Record<string, ManualValue>, score: any) => void;
  focus?: number; compact?: boolean;
}) {
  const [vals, setVals] = useState(values);
  // keep in step when scores are set elsewhere (e.g. keyboard in Review)
  useEffect(() => { setVals(values); }, [values]);
  const [saving, setSaving] = useState<string | null>(null);
  const set = async (key: string, v: number | null) => {
    setSaving(key);
    try {
      const r = await api.setManual(num, key, v);
      setVals(r.values);
      onChange?.(r.values, r.score);
    } finally { setSaving(null); }
  };
  if (!criteria.length) {
    return <div className="faint small">This buy box has no criteria of your own yet. Add some on the <a href="/buy-box">Buy box</a> page.</div>;
  }
  const scored = criteria.filter((c) => vals[c.key]).length;
  return (
    <div>
      {!compact && <div className="label" style={{ marginBottom: 4 }}>{scored} of {criteria.length} scored · 0 = poor, 5 = excellent</div>}
      {criteria.map((c, i) => {
        const v = vals[c.key]?.value;
        return (
          <div key={c.key} className={`myscore ${focus === i ? "focus" : ""}`}>
            <span className="lab">{compact && <span className="kbd" style={{ marginRight: 6 }}>{i + 1}</span>}{c.label}
              <span className="faint small"> · counts {c.weight}</span></span>
            <span className="pips" aria-label={`${c.label} score`}>
              {[0, 1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" disabled={saving === c.key}
                        className={v === n ? `on ${n <= 1 ? "low" : n <= 3 ? "mid" : ""}` : ""}
                        onClick={() => set(c.key, v === n ? null : n)} aria-pressed={v === n}>{n}</button>
              ))}
            </span>
            {c.help && <span className="help">{c.help}</span>}
          </div>
        );
      })}
    </div>
  );
}

export const toNum = (v: string | number | null | undefined): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

export function money(v: string | number | null | undefined, opts: { precise?: boolean } = {}): string {
  const n = toNum(v);
  if (n === null || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "−" : "";
  const a = Math.abs(n);
  if (opts.precise) return sign + "£" + a.toLocaleString("en-GB", { maximumFractionDigits: 0 });
  if (a >= 1_000_000) return `${sign}£${(a / 1_000_000).toFixed(a >= 10_000_000 ? 0 : 1)}m`;
  if (a >= 1_000) return `${sign}£${Math.round(a / 1_000)}k`;
  return `${sign}£${Math.round(a)}`;
}

export function range(lo: string | number | null, hi: string | number | null): string {
  const a = toNum(lo), b = toNum(hi);
  if (a === null) return "—";
  if (b === null || a === b) return money(a);
  return `${money(a)}–${money(b).replace("£", "")}`;
}

export function int(v: number | string | null | undefined): string {
  const n = toNum(v);
  return n === null ? "—" : n.toLocaleString("en-GB");
}

export function date(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function years(since: string | null): string {
  if (!since) return "—";
  const y = (Date.now() - new Date(since).getTime()) / (365.25 * 864e5);
  return `${Math.floor(y)}`;
}

export const ageFrom = (birthYear: number | null | undefined) =>
  birthYear ? new Date().getFullYear() - birthYear : null;

export const OWNERSHIP: Record<string, string> = {
  owner_held: "Owner-held",
  group_owned: "Group-owned",
  investor_backed: "Investor-backed",
  eot: "Employee-owned",
  trust: "Held in trust",
  foreign_owned: "Foreign parent",
  unknown: "Not traced",
};

export const FLAGS: Record<string, string> = {
  via_holdco: "via holdco",
  recent_change: "recent ownership change",
  foreign_parent: "foreign parent",
  eot: "EOT",
  trust: "trust",
  investor: "investor",
  no_psc_data: "no owner data",
  ch_default: "CH default address",
  formation_agent: "formation-agent address",
  mass_address: "shared address",
};

export const LINK_KIND: Record<string, string> = {
  owned_by: "Ownership",
  shared_owner: "Same owner",
  shared_address: "Same address",
};

export const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function chUrl(num: string) {
  return `https://find-and-update.company-information.service.gov.uk/company/${num}`;
}

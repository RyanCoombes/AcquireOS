export type Status = "new" | "watching" | "researching" | "approach" | "contacted" | "in_talks" | "nda" | "offer"
  | "heads" | "diligence" | "spa" | "completion" | "handover" | "passed" | "rejected";

export interface Stage { value: Status; label: string; phase: string; description: string; checklist: string[] }
export interface Task { item_key: string; label: string; custom: boolean; done: boolean; done_at: string | null; note: string | null }
export interface Deal {
  history: { from_status: Status | null; to_status: Status; note: string | null; created_at: string }[];
  tasks: Record<string, Task[]>;
  stage_entered_at: string | null;
}

export interface Meta {
  version: string;
  statuses: { value: Status; label: string; phase?: string }[];
  stages: Stage[];
  phases: { value: string; label: string }[];
  ownership_types: { value: string; label: string }[];
  address_flags: Record<string, string>;
  regions: string[];
  tiers: string[];
  counts: { companies: number; in_scope: number; tracked: number; owner_records: number; last_import: string | null; changed_30d: number };
  company_statuses: string[];
  status_groups: { value: string; label: string }[];
  account_sizes: { value: string; label: string }[];
  map: { tiles: string; attribution: string };
  buy_boxes: { id: number; name: string; is_active: boolean; scored_at: string | null }[];
  buy_box: { id: number; name: string };
}

export interface Row {
  company_number: string;
  name: string;
  region: string | null;
  postcode: string | null;
  review_tier: string | null;
  incorporation_date: string | null;
  sic_codes: string[];
  address_flag: string | null;
  company_status: string | null;
  employees: number | null;
  net_assets: string | null;
  period_end: string | null;
  revenue_low: string | null;
  revenue_high: string | null;
  revenue_basis: string | null;
  ownership_type: string | null;
  oldest_birth_year: number | null;
  flags: string[] | null;
  score: string | null;
  coverage: string | null;
  excluded: boolean | null;
  exclusion: string | null;
  status: Status;
  rating: number | null;
  next_action: string | null;
  next_action_on: string | null;
  value_low: string | null;
  value_high: string | null;
  value_basis: string | null;
  last_change: string | null;
  last_kinds: string[] | null;
  staff_trend: number[] | null;
  website?: string | null;
  business_type?: string | null;
  box_name?: string | null;
  boxes?: string[] | null;
  accounts_category?: string | null;
  charges_outstanding?: number | null;
  accounts_overdue?: boolean | null;
  confirmation_overdue?: boolean | null;
}

export interface Change {
  id: number; company_number: string; kind: string; field: string | null; old_value: string | null;
  new_value: string | null; detected_at: string; filename?: string | null;
  name?: string; company_status?: string | null; status?: Status; score?: string | null; excluded?: boolean | null;
}

export interface Valuation {
  ebitda_low: number | null; ebitda_high: number | null; value_low: number | null; value_high: number | null;
  basis: string | null; steps: string[]; cash: number | string | null;
  assumptions: Assumptions; defaults: Assumptions; override: Partial<Assumptions>;
}
export interface Assumptions { margin_low: number; margin_high: number; multiple_low: number; multiple_high: number }

export interface SavedSearch { id: number; name: string; params: Record<string, string>; buy_box_id?: number | null; buy_box_name?: string | null }
export interface ManualCriterion { key: string; label: string; weight: number; help?: string; boxes?: string[] }
export interface ManualValue { criterion_key: string; value: number; note: string | null; updated_at: string }
export interface BuyBoxRow {
  id: number; name: string; description: string | null; template: string | null; is_active: boolean;
  scored_at: string | null; in_scope: number; strong: number; searches: number;
}

export interface BoxScore { score: string; coverage: string; excluded: boolean; exclusion: string | null; reasons: Reason[] }
export interface Reason { key: string; label: string; points: number; max: number; status: "good" | "partial" | "miss" | "unknown" | "unscored"; text: string; manual?: boolean }

export interface Link {
  lat?: number | null; lon?: number | null;
  kind: "owned_by" | "shared_owner" | "shared_address";
  via: string;
  confidence: "confirmed" | "likely" | "possible";
  evidence: string;
  other: string;
  other_name: string | null;
  direction: "parent" | "subsidiary" | "peer";
  in_list: boolean;
}

export interface Note { id: number; body: string; source: string; created_at: string }

export interface CompanyDetail {
  company: {
    company_number: string; name: string; status: string | null; company_type: string | null;
    incorporation_date: string | null; sic_codes: string[]; nature_of_business: string | null;
    registered_address: string | null; postcode: string | null; address_flag: string | null;
    region: string | null; review_tier: string | null; extra: Record<string, unknown>; source: string | null;
    updated_at: string; dissolution_date: string | null; status_changed_at: string | null; last_accounts_date: string | null;
    accounts_category?: string | null; accounts_next_due?: string | null; confirmation_next_due?: string | null;
    charges_total?: number | null; charges_outstanding?: number | null; charges_part_satisfied?: number | null;
    charges_satisfied?: number | null; previous_names?: { name: string; until: string | null }[] | null;
  };
  financials: {
    period_end: string; period_inferred: boolean; employees: number | null; turnover: string | null;
    profit_loss: string | null; operating_profit: string | null; net_assets: string | null;
    cash: string | null; debtors: string | null; dividends: string | null; source: string | null;
    fixed_assets?: string | null; intangible_assets?: string | null; current_assets?: string | null;
    net_current_assets?: string | null; total_assets_less_cl?: string | null; gross_profit?: string | null;
    director_pay?: string | null; staff_costs?: string | null;
  }[];
  estimate: { revenue_low: string; revenue_high: string; basis: string; method: string } | null;
  ownership: {
    ownership_type: string; flags: string[]; owner_count: number; oldest_birth_year: number | null;
    ultimate_owners: { name: string; birth_year?: number; birth_month?: number; via: string[]; unresolved?: boolean; kind?: string }[];
    explanation: string;
  } | null;
  people: {
    name: string; kind: string; birth_year: number | null; birth_month: number | null; country_registered: string | null;
    registration_number: string | null; role: string; natures: string[]; notified_on: string | null; ceased_on: string | null;
  }[];
  links: Link[];
  score: BoxScore | null;
  scores: (BoxScore & { buy_box_id: number; buy_box: string })[];
  state: { status: Status; rating: number | null; tags: string[]; next_action?: string | null; next_action_on?: string | null; valuation?: Partial<Assumptions> };
  changes: Change[];
  valuation: Valuation;
  deal: Deal;
  manual: { criteria: ManualCriterion[]; values: Record<string, ManualValue> };
  buy_box: { id: number; name: string };
  geo: { lat: number; lon: number; precision: string } | null;
  sics: { code: string; description: string }[];
  enrichment: {
    website: string | null; business_type: string | null; recurring_revenue: string | null; field_service: string | null;
    summary: string | null; confidence: string | null; updated_at: string; updated_by: string | null;
  } | null;
  issues: { id: number; issue: string; detail: string | null; suggested_fix: string | null; status: string; created_by: string | null; created_at: string; resolution: string | null }[];
  notes: Note[];
  research: { id: number; kind: string; content: string; source_url: string | null; source_label: string | null; retrieved_at: string }[];
  outreach: Outreach[];
}

export interface Outreach {
  id: number; company_number: string | null; company_name?: string | null; contact_name: string; contact_role: string;
  channel: string | null; summary: string | null; happened_on: string; next_action: string | null; next_action_on: string | null;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch { /* not json */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export const api = {
  meta: () => req<Meta>("/api/meta"),
  companies: (params: Record<string, string>) =>
    req<{ total: number; capped?: boolean; search_limited?: boolean; rows: Row[] }>("/api/companies?" + new URLSearchParams(params)),
  company: (n: string, bb?: number | null) =>
    req<CompanyDetail>(`/api/companies/${encodeURIComponent(n)}${bb ? `?bb=${bb}` : ""}`),
  setState: (n: string, body: Record<string, unknown>) =>
    req(`/api/companies/${encodeURIComponent(n)}/state`, { method: "PUT", body: JSON.stringify(body) }),
  addNote: (n: string, body: string) =>
    req<Note>(`/api/companies/${encodeURIComponent(n)}/notes`, { method: "POST", body: JSON.stringify({ body }) }),
  addResearch: (n: string, body: Record<string, unknown>) =>
    req(`/api/companies/${encodeURIComponent(n)}/research`, { method: "POST", body: JSON.stringify(body) }),
  pipeline: () => req<{ statuses: Stage[]; phases: { value: string; label: string }[];
    rows: (Row & { last_note: string | null; stage_entered_at: string | null; tasks_done: number; tasks_total: number })[] }>("/api/pipeline"),
  setTask: (n: string, body: Record<string, unknown>) =>
    req<Deal>(`/api/companies/${encodeURIComponent(n)}/tasks`, { method: "POST", body: JSON.stringify(body) }),
  outreach: () => req<Outreach[]>("/api/outreach"),
  addOutreach: (body: Record<string, unknown>) => req<Outreach>("/api/outreach", { method: "POST", body: JSON.stringify(body) }),
  reports: () => req<Record<string, any>>("/api/reports"),
  graph: (n: string, depth = 2) => req<{ nodes: GNode[]; edges: GEdge[] }>(`/api/links/${encodeURIComponent(n)}?depth=${depth}`),
  buybox: (id?: number | null) =>
    req<{ id: number; name: string; description: string | null; criteria: any; defaults: any }>(`/api/buybox${id ? `?id=${id}` : ""}`),
  saveBuybox: (id: number, criteria: any) =>
    req<{ rescored: number; background?: boolean; queued?: boolean }>(`/api/buybox?id=${id}`, { method: "PUT", body: JSON.stringify({ criteria }) }),
  preview: (kind: string, file: File, sheet?: string) => {
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", file);
    if (sheet) fd.append("sheet", sheet);
    return req<Preview>("/api/import/preview", { method: "POST", body: fd });
  },
  commit: (body: Record<string, unknown>) =>
    req<{ rows_in: number; rows_ok: number; rows_skipped: number; notes_added?: number; changes?: number; messages: string[] }>(
      "/api/import/commit", { method: "POST", body: JSON.stringify(body) }),
  imports: () => req<any[]>("/api/imports"),
  coverage: () => req<Record<string, any>>("/api/coverage"),
  dashboard: () => req<Record<string, any>>("/api/dashboard"),
  mapData: (params: Record<string, string>) => req<Record<string, any>>("/api/companies?" + new URLSearchParams(params)),
  geocodeStatus: () => req<Record<string, any>>("/api/geocode"),
  startGeocode: () => req<Record<string, any>>("/api/geocode", { method: "POST" }),
  sic: () => req<{ code: string; n: number; in_scope: number; description: string }[]>("/api/sic"),
  connect: () => req<Record<string, any>>("/api/connect"),
  issues: (status = "open") => req<any[]>(`/api/issues?status=${status}`),
  addIssue: (body: Record<string, unknown>) => req("/api/issues", { method: "POST", body: JSON.stringify(body) }),
  resolveIssue: (id: number, status: string, resolution: string) =>
    req(`/api/issues/${id}/resolve`, { method: "POST", body: JSON.stringify({ status, resolution }) }),
  saveEnrichment: (n: string, body: Record<string, unknown>) =>
    req(`/api/companies/${encodeURIComponent(n)}/enrichment`, { method: "POST", body: JSON.stringify(body) }),
  startRefresh: (months = 1, reread = false) =>
    req<Record<string, any>>(`/api/refresh?months=${months}${reread ? "&reread=true" : ""}`, { method: "POST" }),
  refreshStatus: () => req<Record<string, any>>("/api/refresh"),
  jobCurrent: () => req<Job>("/api/jobs/current"),
  buyboxes: () => req<BuyBoxRow[]>("/api/buyboxes"),
  buyboxTemplates: () => req<{ key: string; label: string; description: string }[]>("/api/buybox-templates"),
  createBuybox: (body: Record<string, unknown>) => req<BuyBoxRow & { background: boolean }>("/api/buyboxes", { method: "POST", body: JSON.stringify(body) }),
  activateBuybox: (id: number) => req<{ ok: boolean; scoring: boolean }>(`/api/buyboxes/${id}/activate`, { method: "POST" }),
  renameBuybox: (id: number, body: Record<string, unknown>) => req(`/api/buyboxes/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteBuybox: (id: number) => req(`/api/buyboxes/${id}`, { method: "DELETE" }),
  setManual: (n: string, key: string, value: number | null, note?: string) =>
    req<{ score: any; values: Record<string, ManualValue> }>(`/api/companies/${encodeURIComponent(n)}/manual`,
      { method: "PUT", body: JSON.stringify({ key, value, note }) }),
  review: (params: Record<string, string>) =>
    req<{ total: number; rows: { company_number: string; name: string; score: string | null }[] }>("/api/review?" + new URLSearchParams(params)),
  dashboardFor: (bb: string) => req<Record<string, any>>(`/api/dashboard?bb=${encodeURIComponent(bb)}`),
  cancelJob: (id: number) => req<{ ok: boolean; message: string }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  changes: (params: Record<string, string>) =>
    req<{ rows: Change[]; summary: { kind: string; n: number }[] }>("/api/changes?" + new URLSearchParams(params)),
  searches: () => req<SavedSearch[]>("/api/searches"),
  saveSearch: (name: string, params: Record<string, string>) =>
    req<SavedSearch>("/api/searches", { method: "POST", body: JSON.stringify({ name, params }) }),
  deleteSearch: (id: number) => req(`/api/searches/${id}`, { method: "DELETE" }),
};

export interface GNode { id: string; name: string; depth: number; in_list: boolean }
export interface GEdge { source: string; target: string; kind: Link["kind"]; via: string; confidence: Link["confidence"]; evidence: string }

export interface Preview {
  headers: string[]; mapping: Record<string, any>; row_count: number | null; sample: Record<string, unknown>[];
  fields: string[]; problems: string[]; token: string; suffix: string; filename: string; sheets: string[]; unmapped?: string[];
}

export interface Job {
  running: boolean;
  id?: number; kind?: string; status?: "running" | "done" | "failed" | "cancelled";
  stage?: string | null; stage_index?: number; stage_total?: number; stage_pct?: string | number; pct?: string | number;
  detail?: string | null; eta_seconds?: number | null;
  stages?: { name: string; status: string; seconds: number | null }[];
  log?: string[]; result?: Record<string, any> | null; error?: string | null;
  started_at?: string; updated_at?: string; finished_at?: string | null; cancel_requested?: boolean;
}

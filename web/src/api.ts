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
  counts: { companies: number; in_scope: number; tracked: number; owner_records: number; last_import: string | null; changed_30d: number; pipeline_new?: number };
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
  revenue_basis: string | null; revenue_method?: string | null;
  signals?: string[]; same_business?: string[]; trading_region?: string | null;
  sold_on?: string | null; sold_to?: string | null;
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
  operating_profit?: string | null; cash?: string | null; da?: string | null; bank_debt?: string | null;
  value_basis: string | null;
  last_change: string | null;
  last_kinds: string[] | null;
  staff_trend: number[] | null;
  website?: string | null;
  business_type?: string | null;
  box_name?: string | null;
  boxes?: string[] | null;
  accounts_category?: string | null;
  matched_owner?: string | null;
  charges_outstanding?: number | null;
  accounts_overdue?: boolean | null;
  confirmation_overdue?: boolean | null;
}

export interface WatchRow {
  id: number; kind: "company" | "owner" | "director"; ref: string; label: string | null; since: string;
  name?: string; status?: string | null; my_status?: string | null; last_change?: string | null; changes_since?: number;
  companies?: { company_number: string; name: string; status: string | null }[]; checked_at?: string | null;
}

export interface ChSync {
  enabled: boolean; paused: boolean; running: boolean; state: string | null; last_beat: string | null;
  pipeline: { total: number; fetched: number; current: number }; targets: { total: number; fetched: number; current: number };
  last_24h: { fetched: number; checked: number }; changes_7d: number; pipeline_days: number; target_days: number;
  days_to_cover: number | null; per_hour: number | null;
  stream?: { enabled: boolean; live: boolean; waiting: number; status_changes?: number; marked?: number; since?: string;
             streams: Record<string, { connected: boolean; events: number; last_at: string | null; error: string | null }> };
}

export interface Change {
  id: number; company_number: string; kind: string; field: string | null; old_value: string | null;
  new_value: string | null; detected_at: string; filename?: string | null; source?: string | null; unread?: boolean;
  name?: string; company_status?: string | null; status?: Status; score?: string | null; excluded?: boolean | null;
}

export interface Valuation {
  ebitda_low: number | null; ebitda_high: number | null; value_low: number | null; value_high: number | null;
  basis: string | null; steps: string[]; cash: number | string | null;
  assumptions: Assumptions; defaults: Assumptions; override: Partial<Assumptions>;
  filed_margin?: number | null; filed_margin_period?: string | null;
}
export interface Funding {
  price: number; your_cash: number; investor_equity: number; investor_stake: number; investor_loan: number;
  investor_rate: number; investor_years: number; vendor_loan: number; vendor_rate: number; vendor_years: number;
  bank_rate: number; bank_years: number;
  addback_owner_pay: number; addback_other: number; new_salaries: number; new_oncost: number;
  bank_amount: number; balance_src: number;
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
    depreciation?: string | null; amortisation?: string | null; depreciation_amortisation?: string | null;
    interest_payable?: string | null; tax?: string | null; creditors_within?: string | null; creditors_after?: string | null;
    bank_loans?: string | null; bank_overdrafts?: string | null; stock?: string | null; trade_debtors?: string | null;
    trade_creditors?: string | null; retained_earnings?: string | null; share_capital?: string | null; principal_activity?: string | null;
  }[];
  pdf_waiting?: string[];
  pdf_reads?: { made_up: string; status: "done" | "nothing_found" | "failed"; method: string | null; note: string | null; read_at: string }[];
  estimate: { revenue_low: string; revenue_high: string; basis: string; method: string } | null;
  ownership: {
    ownership_type: string; flags: string[]; owner_count: number; oldest_birth_year: number | null;
    ultimate_owners: { name: string; birth_year?: number; birth_month?: number; via: string[]; unresolved?: boolean; kind?: string; person_id?: number }[];
    explanation: string;
  } | null;
  people: {
    person_id: number; name: string; kind: string; birth_year: number | null; birth_month: number | null; country_registered: string | null;
    registration_number: string | null; role: string; natures: string[]; notified_on: string | null; ceased_on: string | null;
  }[];
  links: Link[];
  score: BoxScore | null;
  scores: (BoxScore & { buy_box_id: number; buy_box: string })[];
  state: { status: Status; rating: number | null; tags: string[]; next_action?: string | null; next_action_on?: string | null; valuation?: Partial<Assumptions>; funding?: Partial<Funding> };
  changes: Change[];
  valuation: Valuation;
  deal: Deal;
  signals?: string[];
  watching?: boolean; watched_officers?: string[]; watched_owners?: string[];
  sold?: { sold_on: string | null; sold_to: string | null } | null;
  same_business?: { company_number: string; name: string; postcode: string | null; employees: number | null;
                    revenue_low: string | null; revenue_high: string | null; revenue_basis: string | null }[];
  manual: { criteria: ManualCriterion[]; values: Record<string, ManualValue> };
  buy_box: { id: number; name: string };
  geo: { lat: number; lon: number; precision: string } | null;
  sics: { code: string; description: string }[];
  enrichment: {
    website: string | null; business_type: string | null; recurring_revenue: string | null; field_service: string | null;
    summary: string | null; confidence: string | null; updated_at: string; updated_by: string | null;
    linkedin?: string | null; phone?: string | null;
    ownership?: string | null; ownership_note?: string | null; trading_postcode?: string | null; trading_region?: string | null;
    locations?: { name: string | null; address: string | null; postcode: string | null; kind: string; lat?: number | null; lon?: number | null }[];
    facts?: { label: string; value: string; source_url: string | null }[];
    links?: { title: string; url: string; date: string | null; kind: string }[] | null;
  } | null;
  issues: { id: number; issue: string; detail: string | null; suggested_fix: string | null; status: string; created_by: string | null; created_at: string; resolution: string | null }[];
  notes: Note[];
  fin_summary?: {
    period_end: string | null; previous_end?: string | null; months?: number | null;
    rows: { key: string; label: string; value: number; change: number | null; change_pct: number | null; good: boolean | null; trend: string; estimated?: boolean }[];
    series: { period_end: string; total_assets: number | null; total_liabilities: number | null; net_assets: number | null;
              debt_ratio: number | null; cash: number | null; turnover: number | null; employees: number | null;
              turnover_est?: number | null; turnover_basis?: string | null; turnover_est_from?: string | null }[];
  };
  ch?: {
    enabled: boolean;
    fetched: { fetched_at: string; checked_at?: string | null; error: string | null; profile: Record<string, any>; insolvency: any[];
               psc_statements: { statement: string; notified_on: string | null; ceased_on: string | null }[];
               shareholders_from: string | null;
               psc?: { name: string; kind: string; natures: string[]; notified_on: string | null; ceased_on: string | null;
                       birth_year: number | null; birth_month: number | null; registration_number: string | null;
                       country_registered: string | null }[] | null } | null;
    officers: { officer_key: string; name: string; role: string | null; appointed_on: string | null; resigned_on: string | null;
                birth_year: number | null; birth_month: number | null; occupation: string | null; nationality: string | null; residence?: string | null;
                other_current: number; other_total: number }[];
    other_appointments: { officer_key: string; officer_name: string; company_number: string; company_name: string | null;
                          company_status: string | null; role: string | null; appointed_on: string | null; resigned_on: string | null;
                          name_on_register: string | null; score: string | null }[];
    shareholders: { name: string; shares: number | null; share_class: string | null; as_at: string | null; source: string | null; pct: number | null }[];
    disqualified?: { officer_key: string; name: string; disqualified_from: string | null; disqualified_until: string | null; reason: string | null; company_names: string[] | null }[];
    exemptions?: { kind: string; from: string | null; to: string | null }[];
    late_filings: { made_up_to: string; filed_on: string; days_late: number }[];
    charges: { charge_id: string; status: string | null; classification: string | null; holders: string[]; created_on: string | null;
               satisfied_on: string | null; particulars: string | null }[];
    filings: { transaction_id: string; filed_on: string | null; type: string | null; description: string | null }[];
    signals: { kind: string; strength: "strong" | "possible"; text: string; date: string | null }[];
  };
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

let metaCache: { t: number; p: Promise<Meta> } | null = null;

export const api = {
  // Every page asks for meta; one request serves them all for 20 seconds.
  meta: () => {
    if (!metaCache || Date.now() - metaCache.t > 20_000) metaCache = { t: Date.now(), p: req<Meta>("/api/meta") };
    return metaCache.p;
  },
  companiesCount: (params: Record<string, string>) =>
    req<{ total: number; capped: boolean }>("/api/companies?" + new URLSearchParams({ ...params, format: "count" })),
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
  fetchDetails: (n: string) => req<CompanyDetail["ch"]>(`/api/companies/${encodeURIComponent(n)}/fetch-details`, { method: "POST" }),
  removeWebsite: (n: string) => req<{ removed: string | null }>(`/api/companies/${encodeURIComponent(n)}/website`, { method: "DELETE" }),
  findWebsite: (n: string, url?: string, save = false) =>
    req<{ results: { url: string; reachable: boolean; confidence: "high" | "medium" | "low" | null; evidence: string; page?: string; title?: string | null }[];
          saved: string[] | null; message: string }>(`/api/companies/${encodeURIComponent(n)}/find-website`,
      { method: "POST", body: JSON.stringify({ url: url ?? null, save }) }),
  chCheck: (n: string) => req<NonNullable<CompanyDetail["ch"]> & { changed: boolean; changes: number }>(
    `/api/companies/${encodeURIComponent(n)}/ch-check`, { method: "POST" }),
  catchUp: () => req<{ accounts_months_old: number; accounts_months_current: number; accounts_months_total: number; loader_version: number; owners_current?: boolean }>("/api/catch-up"),
  reclassifyOwners: () => req<{ started: boolean }>("/api/ownership/reclassify", { method: "POST" }),
  chExtras: () => req<ChExtras>("/api/ch-extras"),
  chExtrasSet: (paused: boolean) => req<ChExtras>("/api/ch-extras", { method: "PUT", body: JSON.stringify({ paused }) }),
  pdfRead: () => req<PdfRead>("/api/pdf-read"),
  pdfFailures: () => req<PdfFailure[]>("/api/pdf-read/failures"),
  pdfRetry: (num?: string) => req<PdfRead & { requeued: number }>(`/api/pdf-read/retry${num ? `?company_number=${encodeURIComponent(num)}` : ""}`, { method: "POST" }),
  refreshCompany: (n: string) => req<{ changes: number; accounts_added: number; error: string | null; pdf_reading: string[] }>(
    `/api/companies/${encodeURIComponent(n)}/refresh`, { method: "POST" }),
  pdfRedo: () => req<PdfRead & { figures_cleared: number; companies: number; years_queued: number }>("/api/pdf-read/redo", { method: "POST" }),
  pdfSuspicious: () => req<Suspicious[]>("/api/pdf-read/suspicious"),
  pdfYears: (show: "check" | "all", q?: string) =>
    req<PdfYear[]>(`/api/pdf-read/years?show=${show}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  pdfCheck: (num: string, pe: string) =>
    req<PdfCheck>(`/api/pdf-read/check?company_number=${encodeURIComponent(num)}&period_end=${encodeURIComponent(pe)}`),
  pdfCorrect: (company_number: string, period_end: string, values: Record<string, number | null>) =>
    req<{ changed: string[] }>("/api/pdf-read/correct", { method: "POST", body: JSON.stringify({ company_number, period_end, values }) }),
  pdfChecked: (company_number: string, period_end: string) => req<{ ok: boolean }>("/api/pdf-read/checked", { method: "POST", body: JSON.stringify({ company_number, period_end }) }),
  pdfClose: (company_number: string, made_up: string, reason: string) =>
    req<PdfRead & { closed: number }>("/api/pdf-read/close", { method: "POST", body: JSON.stringify({ company_number, made_up, reason }) }),
  pdfReadSet: (paused: boolean) => req<PdfRead>("/api/pdf-read", { method: "PUT", body: JSON.stringify({ paused }) }),
  chSync: () => req<ChSync>("/api/ch-sync"),
  chSyncSet: (paused: boolean) => req<ChSync>("/api/ch-sync", { method: "PUT", body: JSON.stringify({ paused }) }),
  watchList: () => req<{ rows: WatchRow[] }>("/api/watch"),
  watch: (kind: string, ref: string, label?: string) =>
    req<{ id: number }>("/api/watch", { method: "POST", body: JSON.stringify({ kind, ref, label }) }),
  unwatch: (kind: string, ref: string) =>
    req<{ ok: boolean }>(`/api/watch?kind=${encodeURIComponent(kind)}&ref=${encodeURIComponent(ref)}`, { method: "DELETE" }),
  websiteSummary: () => req<{ checked: number; confirmed: number; possible: number; none: number; last_at: string | null; with_website: number }>("/api/website-check"),
  websiteCheck: (scope: string, limit: number) =>
    req<{ started: boolean }>(`/api/website-check?scope=${scope}&limit=${limit}`, { method: "POST" }),
  chDetailsBatch: (scope: string, limit: number) =>
    req<{ started: boolean }>(`/api/ch-details?scope=${scope}&limit=${limit}`, { method: "POST" }),
  researchBrief: (n: string) => req<Record<string, any>>(`/api/companies/${encodeURIComponent(n)}/research-brief`),
  compare: (n: string) => req<{ peers: number; group: string | null; metrics: { key: string; label: string; fmt: "money" | "pct"; value: number | null; pct: number | null; median: number | null; n: number }[] }>(
    `/api/companies/${encodeURIComponent(n)}/compare`),
  network: (id: string, former = false) =>
    req<{ node: import("./components/Network").NNode | null; nodes: import("./components/Network").NNode[]; edges: import("./components/Network").NEdge[] }>(
      `/api/network/${encodeURIComponent(id)}${former ? "?former=true" : ""}`),
  owners: (q: string) => req<{ rows: OwnerHit[] }>("/api/owners?" + new URLSearchParams({ q })),
  owner: (id: number) => req<OwnerDetail>(`/api/owners/${id}`),
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
  bulkState: (body: Record<string, unknown>) =>
    req<{ updated: number }>("/api/companies/state", { method: "PUT", body: JSON.stringify(body) }),
  setManual: (n: string, key: string, value: number | null, note?: string) =>
    req<{ score: any; values: Record<string, ManualValue> }>(`/api/companies/${encodeURIComponent(n)}/manual`,
      { method: "PUT", body: JSON.stringify({ key, value, note }) }),
  review: (params: Record<string, string>) =>
    req<{ total: number; rows: { company_number: string; name: string; score: string | null }[] }>("/api/review?" + new URLSearchParams(params)),
  dashboardFor: (bb: string) => req<Record<string, any>>(`/api/dashboard?bb=${encodeURIComponent(bb)}`),
  cancelJob: (id: number) => req<{ ok: boolean; message: string }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  changes: (params: Record<string, string>) =>
    req<{ rows: Change[]; summary: { kind: string; n: number }[]; unread: number }>("/api/changes?" + new URLSearchParams(params)),
  changesSeen: () => req<{ ok: boolean }>("/api/changes/seen", { method: "POST" }),
  changesRead: (ids: number[]) => req<{ ok: boolean }>("/api/changes/read", { method: "POST", body: JSON.stringify({ ids }) }),
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

export interface OwnerHit {
  id: number; name: string; kind: string; birth_year: number | null; birth_month: number | null;
  country_registered: string | null; registration_number: string | null; companies: number; past: number;
}
export interface OwnerDetail {
  owner: OwnerHit & { legal_form?: string | null; address?: string | null };
  companies: {
    company_number: string; name: string; company_status: string | null; postcode: string | null; region: string | null;
    sic_codes: string[]; incorporation_date: string | null; natures: string[]; notified_on: string | null; ceased_on: string | null;
    employees: number | null; ownership_type: string | null; revenue_low: string | null; revenue_high: string | null;
    revenue_basis: string | null; score: string | null; box_name: string | null; status: string;
  }[];
  indirect: { company_number: string; name: string; company_status: string | null; score: string | null; status: string; via: string | null }[];
  outside_register: number;
}

export type PdfFailure = { company_number: string; name: string; made_up: string; status: string; method: string | null;
  note: string | null; read_at: string; tries: number; sample: string | null };
export type PdfRead = { done: number; by_ocr: number; by_data?: number; by_claude?: number; closed?: number; nothing_found: number; failed: number; last_at: string | null;
  queue: number; ocr: boolean; paused: boolean; suspicious?: number };
export type PdfYear = { company_number: string; name: string; period_end: string; made_up: string; method?: string | null;
  read_at?: string; checked: boolean; why: string[] };
export type PdfCheck = { company_number: string; name: string; period_end: string; source: string | null;
  figures: Record<string, number | null>; made_up: string | null; column: "current" | "prior" | null; method: string | null;
  note: string | null; read_at: string | null; text: string | null; full: boolean; lines: Record<string, string>;
  why: string[]; checked: boolean };
export type Suspicious = { company_number: string; name: string; period_end: string; source: string; turnover: number | null;
  gross_profit: number | null; operating_profit: number | null; net_assets: number | null; cash: number | null;
  employees: number | null; why: string[] };

export type ChExtras = { directors_total: number; directors_checked: number; disqualified_found: number; disqualified_known: number;
  companies_total: number; companies_done: number; paused: boolean };

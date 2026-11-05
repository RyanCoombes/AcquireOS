# AcquireOS

Acquisition research for UK private companies, built on free Companies House
data. It turns your search files into a ranked, explained and trackable list
of targets.

- **Home**: headline numbers, best new targets, what changed, staff trend
  across your buy box, next actions, score spread, funnel and ownership mix.
- **Targets**: three views (fits my buy box, all companies, changed
  recently), filters for staff, owner age, ownership, region, status, score,
  company status, SIC code, years trading, indicative value, changes and
  flags, and **saved searches**. Keyboard: `/` search, `j`/`k` move,
  `Enter` open.
- **Changes**: every re-import is compared with what was stored before.
  New accounts, staff changes, status changes (dissolved, liquidation,
  proposal to strike off), renames, office moves, SIC changes and owner
  changes are recorded, listed by date and marked in the targets list.
- **Indicative value**: profit from filed operating profit, or revenue ×
  margin; value = profit × multiple. Assumptions are set in the buy box and
  can be overridden per company. A funding check works out debt cover for a
  given price, equity, vendor loan and bank terms.
- **Company page**: why it scored what it did (a reason for every point),
  financial history charts, owners traced through holding companies,
  connections to other companies, research with sources, and your own call:
  status, rating, next action, notes and outreach.
- **Connections**: a map of companies linked by ownership, by the same owner
  (name and birth date match), or by the same registered address, each with
  a confidence level.
- **Reports**: funnel, score spread, staff sizes, ownership, owner ages,
  exclusions, regions, flags.
- **Buy box**: weights and ranges for each criterion, exclusions by keyword,
  region, tier, ownership and address type. Saving rescores everything.
- **Import**: CSV or Excel, with a preview of how each column will be read.

Your notes, ratings and decisions are stored apart from imported data.
Re-importing or refreshing never overwrites them.

## Buy boxes, your own scores and Review

- **Several buy boxes.** Each is its own search: universe (SIC codes, name
  keywords, postcode areas, age), scoring weights, exclusions, valuation
  assumptions and your own criteria. Start one blank, as a copy, or from a
  template (Managed IT services, Software and SaaS, Data and analytics,
  FMCG); templates are starting points to edit. Switch from the sidebar.
  Your pipeline, notes, stages and your own scores are shared across all of
  them. Saved searches belong to the buy box they were saved in.
- **Your own criteria.** Each buy box can have criteria only you can judge
  (recurring revenue quality, customer spread, owner open to selling, team
  beyond the owner…). You score a company 0–5 on each; the buy box decides
  how much each counts. Unscored criteria are left out of the total, so
  companies you have not reviewed are neither helped nor hurt. Scores belong
  to the company, so a criterion used in several buy boxes is scored once.
- **Review.** One company at a time, best score first: key facts, charts and
  score reasons on the left; on the right, score your criteria with the
  number keys and decide with one key (S shortlist, A assess further,
  W watch, P pass, R reject, → skip, O open the full page).
- **Home** can show one buy box or an overview of all of them.
- Scores are stored only for companies in each buy box's universe, plus your
  pipeline and anything you have scored, which keeps several buy boxes over
  the whole register to a sensible size.

## Deal stages

Every company moves through your acquisition process, and each move is
logged with its date and an optional note:

| Phase | Stages |
|---|---|
| Assess | New → Watching → Assessing → Shortlisted |
| Engage | First contact → Getting to know → NDA and accounts |
| Deal | Indicative offer → Heads of terms → Due diligence → SPA and disclosure → Completion |
| Owned | Handover |
| Closed | Passed, Rejected |

Each stage has a checklist (for example, Assessing: accounts reviewed,
website checked, owners confirmed, recurring revenue estimated, no
field-service red flags, rough value done), and you can add your own items.
The **Pipeline** page is a board: drag a card to move it, with checklist
progress and days in stage on each card. The company page shows the stage
tracker, the checklist and the full history.

## Connect Claude (MCP) for questions, auditing and enrichment

AcquireOS includes an MCP server at `http://<pi-address>:8090/mcp`, so Claude
on your computer (Claude Desktop, Cowork or Claude Code) can work with your
data directly. The **Connect Claude** page in the app has copy-and-paste setup.

1. Set `API_TOKEN` in the stack (any long random string, or run
   `docker exec acquireos acquireos new-token`) and redeploy.
2. **Claude Desktop / Cowork**: Settings → Developer → Edit Config, and add:

   ```json
   {
     "mcpServers": {
       "acquireos": {
         "command": "npx",
         "args": ["-y", "mcp-remote", "http://<pi-address>:8090/mcp", "--allow-http",
                  "--header", "Authorization:${AUTH}"],
         "env": { "AUTH": "Bearer <your API_TOKEN>" }
       }
     }
   }
   ```

   This uses the `mcp-remote` bridge (needs Node.js on your computer) because
   the Pi is on your home network. Claude's "Add custom connector" option
   needs a server reachable over HTTPS from the internet.
3. **Claude Code**:
   `claude mcp add --transport http acquireos http://<pi-address>:8090/mcp --header "Authorization: Bearer <token>"`

What Claude can do:

| Tools | Purpose |
|---|---|
| `dataset_overview`, `search_companies`, `get_company`, `list_changes` | Answer questions about targets, owners, financials and changes |
| `describe_database`, `query_database` | Read-only SQL for audits and analysis (15 s limit, 500 rows) |
| `audit_queue` | Companies missing a website, research, owners, filed turnover or a field-service check, or with a SIC code that does not match the name |
| `save_enrichment` | Save website, business type, recurring revenue, field-service work and a summary. **A source URL is required**; the company is rescored at once |
| `flag_data_issue`, `list_data_issues`, `resolve_data_issue` | Problems for you to review |
| `add_note`, `set_status` | Your notes and pipeline, labelled as Claude; only when you ask |

There is also an `audit_and_enrich` prompt that walks Claude through a batch.
Enrichment is stored separately from your own notes and decisions, and every
fact keeps its source link in the company's research history. A company
found to do field-service work is excluded by default (Buy box → Exclusions).

The same token also works for the REST API (`Authorization: Bearer …`), with
interactive documentation at `/docs`.

## Map and SIC codes

Registered offices are placed on an OpenStreetMap map using the free
[postcodes.io](https://postcodes.io) service (ONS open data), cached so each
postcode is looked up once. Retired postcodes fall back to the postcode
district. The **Map** page shows companies coloured by score, with optional
lines to parent companies and to companies sharing an owner; each company page
has its own location map. Locations are looked up after each monthly refresh,
or with **Locate postcodes** on the Map page, or `acquireos geocode`.

OpenStreetMap's own tile server is fine for personal use. For a hosted
product, set `MAP_TILE_URL` and `MAP_ATTRIBUTION` to a commercial tile
provider; heavy use of the free tiles breaks their usage policy.

SIC codes show their descriptions everywhere. Descriptions for IT and
software codes are built in; the rest are learnt from the Companies House
bulk file. Reports include an industry breakdown, and the targets filter
suggests codes as you type.

## Run it on the Raspberry Pi with Portainer

Needs a 64-bit OS on the Pi (Raspberry Pi OS 64-bit, Ubuntu arm64 and so on).

1. **Let the Pi pull the image.** The image is published to GitHub's
   registry (`ghcr.io/ryancoombes/acquireos`) each time `main` changes. While
   the repository is private, so is the image, so either:
   - make the package public (GitHub → your profile → Packages → acquireos →
     Package settings → Change visibility), or
   - in Portainer go to **Registries → Add registry → Custom**, URL `ghcr.io`,
     username `RyanCoombes`, and as the password a GitHub personal access
     token (classic) with only the `read:packages` scope.
2. **Create the stack.** Portainer → **Stacks → Add stack → Web editor**.
   Name it `acquireos` and paste the whole of
   [`docker-compose.yml`](docker-compose.yml).
3. **Set environment variables** (optional: the stack deploys without any).
   Environment variables → Advanced mode, paste and edit. Set `DB_PASSWORD`
   **before the first deploy**: Postgres only reads it when the database is
   first created, so changing it later breaks the connection.

   ```
   DB_PASSWORD=pick-a-long-random-password
   APP_PORT=8090
   DATA_DIR=/opt/acquireos/data
   BACKUP_DIR=/mnt/nas/acquireos
   APP_PASSWORD=
   API_TOKEN=a-long-random-string
   ```

   Set `BACKUP_DIR` to wherever your NAS is mounted on the Pi.
   Set `APP_PASSWORD` if the app will ever be reachable from outside your LAN.
4. **Deploy the stack**, then open `http://<pi-address>:8090`.
5. **Import your data** on the Import page (see below).

To update later: Stacks → acquireos → **Pull and redeploy** (tick
"Re-pull image"). Your data is in the `acquireos-db` volume and survives
updates.

**Building on the Pi instead of pulling:** use Portainer's **Repository**
stack type with this repo, compose path `docker-compose.yml`, and add
`docker-compose.build.yml` as an additional file. The first build on a Pi
takes several minutes.

## Importing your search data

Open **Import**, in this order:

1. **Company data**: `Companies_House_targets_ranked.csv`, the audit
   workbook (733 companies), or any CSV or Excel file with a company number
   column. Columns from the ranked file are recognised automatically;
   anything not recognised is kept as extra detail on each company. Numbers
   that lost their leading zeros in Excel (2511854) are fixed (02511854).
2. **My notes and decisions**: the workbook with your assessments (for
   example a "Ryan Assess" column), decisions and the review log. Note
   columns are detected by name (note, assess, comment, review…) and each
   becomes a dated note. Decision words map to statuses ("Shortlist" →
   To approach, "Reject" → Rejected, "Maybe" → Researching); anything
   unrecognised is kept as a tag. Importing the same file twice adds nothing.
3. **Owners (PSC snapshot)**: too big for the browser. Download the
   [PSC snapshot](https://download.companieshouse.gov.uk/en_pscdata.html)
   zip into `DATA_DIR` on the Pi, then in Portainer open the `acquireos`
   container → **Console** → `/bin/sh`, and run:

   ```bash
   acquireos import-psc /data/persons-with-significant-control-snapshot*.zip
   ```

   If Companies House offers the snapshot in several parts, put them all in
   `DATA_DIR`; the command reads them together. It streams the files, keeps only your companies, then follows corporate
   owners up through holding companies to the people behind them.

To try the app without your data: `acquireos demo` in the container console
loads 320 invented companies.

## The whole UK register

AcquireOS keeps **every** company on the Companies House register (about
5.5 million), every filed set of accounts it loads, and every owner (PSC)
record. Your buy box **universe** (Buy box page) decides which companies count
as targets; the rest stay searchable under Targets → All companies, marked
"outside your universe".

Sizing on a Raspberry Pi 5 (16 GB RAM) with an SSD, based on a 500,000-company
test run scaled up:

| | Estimate |
|---|---|
| Database size with two years of accounts | roughly 20–25 GB |
| Free space needed while a file is processed | a few GB more |
| First company register load | about 30–45 minutes |
| Each month of accounts | tens of minutes (parsed on all CPU cores) |
| Owner snapshot and ownership tracing | under an hour |
| Rescoring everything after a buy box change | a few minutes, in the background |

An SD card is not recommended: it is slow and wears out under a database.

**Date order is protected.** History loads oldest month first; every figure
records which filing it came from and is only replaced by a filing with the
same or a later balance sheet date; a register snapshot can never overwrite a
company with data from an older snapshot. When back-filling history no
changes are recorded, so the Changes page only shows what is genuinely new.

Links between companies (same owner, same address) and map locations are
built for companies in your universe or pipeline, to keep them useful and
the database a sensible size.

## Companies House data, loaded automatically

AcquireOS downloads the free Companies House bulk files itself, keeps only
what matters to you, and deletes each file once read (so the Pi needs room
for one file at a time: a few GB).

| File | What it adds |
|---|---|
| Basic company data (monthly, ~0.5 GB zip, 2.6 GB unzipped) | Every live company. New companies matching your buy box **universe** (SIC codes, name keywords, postcode areas, age) are added; existing ones are updated and changes recorded; companies that leave the register are flagged. |
| Monthly accounts (several GB a month) | Filed accounts (iXBRL) for your companies: staff, turnover, operating profit, profit, net assets, cash, debtors, dividends, for the year and the prior year. This builds the multi-year charts. |
| Owners (PSC snapshot, ~2 GB) | Owners traced through holding companies. |

Three ways to run it:

- **Automatically**: the `scheduler` service in the stack runs it on the 6th
  of each month at 03:00 (change with `REFRESH_DAY`, `REFRESH_HOUR`).
- **From the app**: Data page → Download and load now. Pick 12 or 24 months
  of accounts the first time to build history.
- **Command line**: `acquireos fetch all --months 12`, or
  `acquireos fetch accounts --months 24`.

The data goes into your database, not into this repository: the files are
far too big for Git, they change monthly, and the owner data is personal
data.

## Monthly refresh from Companies House (manual)

Download the free [basic company data](https://download.companieshouse.gov.uk/en_output.html)
zip (all UK companies, updated monthly) into `DATA_DIR` and run, in the
container console:

```bash
acquireos import-companies --only-existing /data/BasicCompanyDataAsOneFile-*.zip
```

It streams the file (no need to unzip, and it never loads the whole thing
into memory), updates only companies already in your list, and records what
changed. Smaller CSV extracts can be uploaded on the Import page with “Only
update companies already in my list” ticked. Note that the bulk file has
accounts dates but no figures, so it flags new accounts without updating
staff or net assets; re-import your accounts-derived file for those.

## What the scores and flags mean

- **Score** is points earned ÷ points possible, out of 100. A criterion with
  no data scores nothing but is shown as "no data", not as a miss, and the
  **coverage** figure says how much of the score could be checked.
- **Indicative value** is a screening estimate, not a valuation. Profit is
  filed operating profit where available (without a depreciation add-back,
  so understated), otherwise revenue × margin (default 8 to 15%). Value is
  profit × multiple (default 3 to 5 times). Cash is shown separately and
  debt is not netted off.
- **Revenue** uses filed turnover when it exists, otherwise staff × £80k to
  £150k per head, and is labelled as an estimate.
- **Prior-year figures** from the ranked file have no date of their own; they
  are placed a year before the accounts date and marked "date inferred".
- **Ownership types**: owner-held (directly or via a holding company),
  group-owned, investor-backed, employee-owned (EOT), held in trust, foreign
  parent, or not traced.
- **Owner age** is from the PSC birth month and year, so it can be a year out.
- **Address flags**: the Companies House default address (Cardiff CF14 8LH),
  well-known formation-agent addresses, and any address shared by more than
  15 companies in your data.
- **Connections**: *confirmed* comes from a registration number on a PSC
  record; *likely* is the same owner name plus birth month and year;
  *possible* is a name match without a birth date, or a shared address.

## Hosting elsewhere later

Nothing ties AcquireOS to the Pi:

- All settings come from environment variables. `DATABASE_URL` can point at
  any Postgres 14+ (Supabase, a managed cloud database and so on); drop the
  `db` service in that case.
- The app container keeps no state, so it can run on any Docker host or
  container platform behind a reverse proxy. Set `APP_PASSWORD`, or put real
  authentication in front of it, before exposing it.
- Every user-owned row (notes, statuses, buy box, outreach) carries a
  `user_id`, so a multi-user hosted version needs no data migration.

Not done yet for a hosted product: real user accounts and sign-in, billing,
per-user data separation in the API, and the UK GDPR work set out in the
product plan.

## Command line

Inside the container (`docker exec -it acquireos sh`):

| Command | What it does |
|---|---|
| `acquireos import-companies FILE…` | Import or refresh company lists (CSV, zipped CSV or Excel) |
| `acquireos import-companies --only-existing FILE` | Refresh only companies already in your list |
| `acquireos import-notes FILE…` | Import your notes and decisions |
| `acquireos import-psc FILE` | Import owners from the PSC snapshot |
| `acquireos import-accounts FILE…` | Import accounts zips you downloaded yourself |
| `acquireos fetch company-data\|accounts\|psc\|all [--months N]` | Download from Companies House and load |
| `acquireos scheduler` | Run the monthly refresh on a schedule (the stack does this) |
| `acquireos preview companies FILE` | Show how a file's columns will be read |
| `acquireos rebuild` | Recompute ownership, links and scores |
| `acquireos demo` | Load fictional demo data, including a later refresh so changes show |

## Backups

The `backup` service writes `acquireos-YYYYMMDD.sql.gz` to `BACKUP_DIR` at
02:30 each night and keeps 30 days. To restore into a fresh stack:

```bash
gunzip -c acquireos-20261104.sql.gz | docker exec -i acquireos-db psql -U acquireos acquireos
```

## Development

```bash
# API (needs a Postgres; set DATABASE_URL)
cd backend && pip install -e ".[dev]" && uvicorn acquireos.api:app --reload
# Web, on http://localhost:5173 with the API proxied
cd web && npm install && npm run dev
# Tests (TEST_DATABASE_URL must point at a throwaway database)
cd backend && pytest
```

Design notes, including the visual rules the interface follows, are in
[docs/DESIGN.md](docs/DESIGN.md).

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
3. **Set environment variables** (Environment variables → Advanced mode,
   paste and edit):

   ```
   DB_PASSWORD=pick-a-long-random-password
   APP_PORT=8090
   DATA_DIR=/opt/acquireos/data
   BACKUP_DIR=/mnt/nas/acquireos
   APP_PASSWORD=
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

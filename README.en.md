<p align="center"><img src="diffdb/images/logo_badge.png" width="104" alt="DiFFDB"></p>

<p align="center">
  <a href="https://github.com/Tony-BlaZeeR/DiFFDB/actions/workflows/ci.yml"><img src="https://github.com/Tony-BlaZeeR/DiFFDB/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/PySide6-6.8-41cd52" alt="PySide6">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

# DiFFDB

> 🇬🇧 English — [🇮🇹 Italiano](README.md)

Compares the **structure** of two databases that are meant to share the same schema
(development, staging, production), shows the differences and generates the SQL script
to align them. With a graphical interface and a CLI you can drop into a pipeline.

## Screenshots

<p align="center"><img src="docs/images/results.png" width="840" alt="Results tab: the differences between PRE and PROD"></p>

<p align="center"><em>The differences between two environments, grouped and colour-coded: what is missing and where, different types and constraints. Tick the entries and generate the SQL alignment script.</em></p>

Two visual variants (Modern / Retro), light and dark themes, a customizable accent
colour — switched live:

<p align="center"><img src="docs/images/themes.gif" width="760" alt="The variant and theme combinations"></p>

<p align="center"><img src="docs/images/connections.png" width="760" alt="Connection management"><br><sub>Connections: passwords live in the OS keyring, never in the file.</sub></p>

## What it detects

- Tables present in one environment and not in the other
- Missing columns, **with a different type, nullability or default value**
- **Indexes, foreign keys, unique constraints, CHECKs and primary keys**
- Views (presence **and definition body**), sequences (with their real
  START/INCREMENT values) and synonyms (Oracle and SQL Server)
- Triggers (presence **and definition body**): no dialect reflects them
  through SQLAlchemy, so they are read with a direct query on the system catalog
- Standalone stored procedures and functions (presence **and definition
  body**), with the same approach as triggers — the members of an Oracle
  package are left out, they are a separate category

## What it produces

- `differenze_ambienti.xlsx` — one sheet for tables, constraints, views,
  sequences, synonyms, triggers, procedures and functions. Each row says *what*
  differs, *where* it is missing and with what *detail*.
- `allinea_<environment>.sql` — one script **per direction**, with executable SQL
  (CREATE TABLE with columns, types and FKs; ALTER TABLE; CREATE INDEX; ADD
  CONSTRAINT; CREATE VIEW; CREATE SEQUENCE; CREATE TRIGGER; CREATE
  PROCEDURE/FUNCTION), compiled for the dialect of the environment to align.
- `annulla_<environment>.sql` — how to undo that alignment (see below).
- `snapshot.json` — the structure of an environment frozen to a file (see below).

DiFFDB proposes, it does not apply: it never runs anything against the compared
databases. Destructive or risky operations (changing a primary key, NOT NULL on
populated tables, constraints on dialects that cannot add them via ALTER) are not
generated as SQL, but flagged as a comment in the script.

## The alignment script

Besides being executable SQL, the script makes sure it **can be run from start
to finish**:

- **New tables come out in dependency order.** Foreign keys live inside the
  `CREATE TABLE`, so in alphabetical order a script that creates `ordini` before
  `clienti` would fail halfway. If there is a cycle between tables no order
  works, and the script says so instead of pretending.
- **It opens a transaction** where the database can roll back DDL:

  | Dialect | Transaction |
  | --- | --- |
  | PostgreSQL, SQL Server, SQLite | `BEGIN` / `COMMIT`: all or nothing |
  | MySQL, Oracle | None: each DDL commits on its own, and the script says so at the top |

  Wrapping Oracle and MySQL in a `BEGIN/COMMIT` would give the illusion of being
  able to undo, which is worse than not having it.

### Rolling back

Alongside every alignment script an **undo** script is written, which reverses
what the first one did. It matters most on Oracle and MySQL, where there is no
transaction — but elsewhere too: a transaction protects during execution, not
from regret the next day.

It is derived from the same differences as the forward pass, not by reversing
the SQL text: reading strings backwards would be fragile, and here mistakes
delete. The sections go in reverse order — views and constraints before tables —
and a column's type goes back to what the environment really had.

It does not undo everything, and does not pretend to: whatever the alignment left
as a comment stays a comment. Where a new column could have held data, the script
warns before dropping it.

The contract is verified on the four real engines: it aligns, it undoes, and the
environment's fingerprint goes back identical to before.

## Supported databases

PostgreSQL, MySQL/MariaDB, Oracle, SQL Server, SQLite — through SQLAlchemy.

## Installation

Requires Python 3.10+.

```sh
pip install diffdb[gui,report,postgresql]   # interface, Excel and the driver you need
diffdb-gui                                  # graphical interface
diffdb PROD PRE --fail-on-diff              # command line
```

Dependencies are split into extras, so a pipeline that only wants the comparison
does not carry Qt and pandas along:

| Extra | What it adds |
| --- | --- |
| `gui` | The graphical interface (PySide6) |
| `report` | The Excel report (pandas, openpyxl) |
| `postgresql`, `mysql`, `oracle`, `mssql` | The matching driver |
| `all` | Everything |

Without `report` the comparison still works: the SQL scripts are written and the
Excel is skipped with a warning, instead of failing the command.

### Executables and installers

Every GitHub release attaches, for each system, both an **installer** and a
**portable** executable (signed where signing is configured):

| System | Installer | Portable |
| --- | --- | --- |
| Windows | `DiFFDB-Setup-x.y.z.exe` | `DiFFDB.exe` |
| macOS | `DiFFDB-x.y.z.dmg` | — |
| Linux | `DiFFDB-x.y.z-x86_64.AppImage` | `DiFFDB-linux-x86_64` |

Next to them is a `SHA256SUMS` file to verify the download.

**Updates.** The **ⓘ** button at the top checks whether a newer version exists
(it opens the releases page). The check is always on request: DiFFDB never
contacts the network on its own, unless you turn on *"Check for updates at
startup"* — off by default, because the program also runs on closed networks.

### From source

```sh
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python main.py
```

The drivers are chosen so they need no system client: `oracledb` runs in *thin
mode* (no Oracle Instant Client to install) and `psycopg2-binary` and `PyMySQL`
have no native dependencies. For SQL Server, `pymssql` carries its own client;
`pyodbc` (commented out in `requirements.txt`) instead requires the ODBC Driver
installed on the machine.

## Connections

They are managed from the **Configuration** tab and end up in `connections.json`,
next to the executable (or in `%APPDATA%\DiFFDB` if that folder is not writable).
The file is **not versioned**: start from `connections.json.example`.

```json
[
  {
    "name": "staging",
    "conn_string": "oracle+oracledb://app:${COL_DB_PWD}@host:1521/?service_name=ORCL",
    "schema": "APP"
  }
]
```

The driver suffix (`+oracledb`, `+pymysql`, `+pymssql`, `+psycopg2`) is
**optional**: if you write just `oracle://`, `mysql://`, `mssql://` or
`postgresql://`, DiFFDB fills in the driver it bundles for you - so you don't
have to remember the right name. Spelling it out still works.

The **schema** is optional: on Oracle it usually matches the user, and it is
needed when the connection user can see more than one schema.

With `DIFFDB_HOME` you can move the configuration wherever you want.

### Passwords do not live in the file

`connections.json` holds a **reference**, never the password:

| Reference | Where the secret really lives |
| --- | --- |
| `${keyring}` | Operating-system keyring: Credential Manager on Windows, Keychain on macOS, Secret Service on Linux |
| `${VARIABLE}` | Environment variable: this is what you use in CI, where the pipeline's secret store keeps the secret |

```sh
python -m diffdb.cli --set-password PROD    # prompts for the password and stores it in the keyring
```

The command stores the password in the keyring and **rewrites the connection in
the file, replacing the password with `${keyring}`**. From the GUI the *Password
in keyring* button in the connection dialog does the same.

This way a `connections.json` copied to another machine contains nothing useful:
the secret is bound to the operating-system user account.

If a password is left in clear text, DiFFDB flags it on every connection. To
**forbid** it entirely:

```sh
DIFFDB_REQUIRE_SECRET_REFS=1    # the connection fails instead of proceeding
```

Connection strings are masked everywhere they leave the process: interface, error
messages, log files and saved snapshots.

## Snapshots: comparing over time, and without the database

A snapshot is the structure of an environment saved to a JSON file. It covers three
things that a live comparison alone cannot do:

- **drift detection** — freeze PROD today, and a month later check what changed;
- **baseline in git** — version the expected schema and fail CI when an
  environment drifts away from it;
- **offline comparison** — the DBA exports the production snapshot and the
  comparison happens elsewhere, with no network access to that database.

A re-read snapshot is an environment in its own right: it is compared and
**generates the alignment script** as if you were connected, because it keeps
types, constraints and dialect. Passwords never go in: the URL is saved masked.

```sh
python -m diffdb.cli PROD --snapshot baseline/prod.json     # freeze
python -m diffdb.cli baseline/prod.json PROD --fail-on-diff  # drift from the baseline
python -m diffdb.cli baseline/prod.json baseline/pre.json    # offline comparison
```

If the two environments share a name (the PROD baseline against today's PROD)
they are told apart automatically: `PROD (prod)` and `PROD (live)`.

From the GUI, in the **Selection** tab: *Save snapshot of the first environment*
and *Compare with a snapshot file*.

## Rules: what to look at, and what has already been decided

On a real schema — two, three thousand tables — a comparison without rules
produces hundreds of differences, most of which are noise: temporary tables,
backup copies, migration leftovers. Nobody reads a list like that.

Rules live in a `diffdb.rules.json` next to the code, **versioned**: exclusions
are team decisions, not preferences of whoever runs the command.

```json
{
  "format": 1,
  "escludi": {
    "tabelle": ["TMP_*", "BCK_*", "*_20??????"],
    "viste": ["V_DEBUG_*"],
    "categorie": ["sequences"]
  },
  "includi_solo": { "tabelle": [] },
  "accettate": []
}
```

Patterns are case-insensitive: Oracle returns names all uppercase and PostgreSQL
all lowercase, and a hand-written pattern must not depend on which of the two you
are looking at.

Filters are applied **before** reading the schema, so they also save the time to
reflect what you will not look at.

You don't have to write the JSON by hand: the **"Comparison filters…"** button
on the *Choose* tab opens an editor that writes and reads back the same
`diffdb.rules.json` — so a filter set from the interface (e.g. *only the tables*
`*T_UTENTE*`) also applies from the CLI and in a pipeline, and stays versionable.

### Accepted differences

There are known and wanted differences: production has an extra index for
performance, staging has a debug column. They should not be excluded by pattern —
that would also hide future ones on the same object — but **accepted once**, to
reappear only if they change:

```sh
diffdb SVI COL --accept        # from here on the comparison is green
diffdb SVI COL --fail-on-diff  # exits 0 until something changes
```

It is the same mechanism as a linter baseline, and it is what makes
`--fail-on-diff` usable in a pipeline on a schema that already starts with known
differences. Without it, the build is red from day one and after a week someone
removes the check.

From the GUI too: on the Results tab, tick the known differences and press
**"Accept selected"**. They disappear from later comparisons (until they change)
and the choice goes into the same `diffdb.rules.json`, so it also applies from the
CLI and in a pipeline.

`--no-rules` ignores the file and shows everything.

**Filters are part of the fingerprint.** Two snapshots taken with different filters
describe different sets: if filters did not enter the fingerprint, `--verify` would
say "all good" on a script generated with other rules.

### On large schemas

The two environments are read **in parallel** — they are independent, and reading
is almost all the time of a comparison. Each connection has a timeout (15
seconds), because without one it inherits the system TCP timeout, which can be
minutes. And in the *Selection* tab a **Cancel** button appears while reading is
in progress: it closes the connections and the comparison stops.

There is also a second timeout, for the query (60 seconds): the first does not
protect from a query that hangs *after* connecting — a huge schema, a lock on a
system table. Each engine exposes it differently: pymssql has a real per-call
timeout passed at connection time, oracledb the same concept but as a property set
on the connection right after connecting, PostgreSQL and MySQL do not have it and
need a session variable (`SET statement_timeout`, `SET SESSION
max_execution_time`) set on every new physical connection. Verified on the four
engines with a query that sleeps longer than the allowed timeout, including the
case that uncovered it: the connection is returned to the pool and then reused a
second time, and the limit must keep applying.

## Traceability: where this script comes from

The `.sql` script DiFFDB produces is a *change* that will end up in production.
Each one carries at the top who generated it, when, comparing what with what, with
which DiFFDB version, and the **fingerprint** of the two environments:

```sql
-- DiFFDB 1.2.0 - alignment script
-- Environment to align  : PROD (oracle, schema APP)
-- Aligned to            : PRE
-- Generated on          : 2026-08-06T10:55:20+00:00
-- Generated by          : user@host
-- Fingerprint of PRE  : sha256:4e093e11...
-- Fingerprint of PROD : sha256:bc78f2ca...
```

The version is there for something non-obvious and very useful: when a fix lands
in the generator, it says **which previously produced scripts are affected**,
instead of having to suspect them all.

The fingerprint makes the script verifiable *before* running it:

```sh
python -m diffdb.cli --verify allinea_prod.sql PROD
```

It exits 0 if the environment is still the one it was when the script was
generated, 1 if it changed in the meantime — in which case the script is no longer
valid and must be regenerated. The fingerprint covers the structure (tables,
views, sequences, synonyms, triggers, procedures and functions, dialect and
schema): renaming an environment or re-taking the snapshot a minute later does not
change it.

The same goes for the Excel, which has an **Info** sheet, and for snapshots, which
carry their own fingerprint inside the file. If you export only part of the
differences, the header says so.

The application log lives in `diffdb.log` next to the configuration, with rotation.

## Accessibility

**Colour is not the only channel.** Every difference also carries a symbol, and a
legend at the top of the results says what it means — before, that meaning existed
only in a comment in the code:

```text
←  missing in DEVELOPMENT      →  missing in STAGING      ≠  present in both but different
```

**Contrast is measured, not estimated.** The colours meet WCAG AA (4.5:1 for text,
3:1 for interface elements) in **every theme** (Modern light/dark and Retro
light/dark), on *every* background they can land on, alternate rows included.
`tests/test_accessibilita.py` computes the ratios on the three palettes and fails
if any drops below the threshold.

**Keyboard.** Shortcuts are scoped to their tab: `Ctrl+S` in the connections tab
exports nothing.

| Shortcut | Action |
| --- | --- |
| `Ctrl+1` … `Ctrl+4` | Go to tab |
| `Ctrl+Enter` | Start the comparison |
| `Ctrl+I` | Invert the direction |
| `F5` | Repeat the comparison |
| `Ctrl+F` | Go to the results filter |
| `Ctrl+E` / `Ctrl+S` | Export Excel / SQL |

**Screen readers.** Icon-only buttons have an accessible name that includes the
object they act on ("Delete the PRODUCTION connection"), not a generic "button".

## Language

The interface speaks **Italian and English**. By default it follows the operating
system language; it is changed from the *Configuration* tab and takes effect on
restart.

The project's source language is Italian: the strings in the code are in Italian
and the `diffdb/translations/diffdb_<lang>.qm` catalogs hold the translations to
the other languages. To add one:

```sh
python tools/traduzioni.py            # updates the .ts and emits the .qm
pyside6-linguist diffdb/translations/diffdb_en.ts    # translate (or edit the .ts by hand)
python tools/traduzioni.py --check    # checks nothing is missing
```

The check also runs in CI: a new untranslated string fails the build, instead of
showing up in Italian inside the English interface.

The interface and the messages the user sees are translated. Logs, the drivers'
technical errors and the comments inside the generated SQL script stay in Italian:
they are diagnostic artifacts, and changing them depending on who produced them
would make them harder to compare.

## Themes and colours

The interface has **two variants**, each in **light and dark**, with a green
palette:

- **Modern** — clean, dark-first, for everyday use;
- **Retro** — terminal/TUI: blocky font, hard edges, titles engraved on the border.

Variant and light/dark are switched on the fly from the buttons in the title bar.
The **accent colour** is chosen from the *Configuration* tab (presets or a free
picker): the shades are derived from the chosen colour, while the diff's semantic
colours stay readable. Preferences are saved and restored on restart.

## Usage (GUI)

1. **Home** — what you compared last time (with *Repeat* to do it again), how the
   configured connections stand, and the two actions to start over.
2. **Configuration** — the connections, with a pill that says **where each
   password lives**: keyring, environment variable or clear text. The *Test
   connection* button actually connects and reports what it found: dialect, server
   version, how many tables it sees and whether the given schema exists — getting
   the schema wrong is the most common mistake, and without this check you find
   out much later, as a comparison that finds nothing.
3. **Selection** — the two environments are chosen side by side, *reference* on the
   left and *to align* on the right, with the ⇄ button to invert the direction.
   Under each dropdown appear dialect, host and schema: swapping staging with
   production is one click, and the name alone is not enough to prevent it.
4. **Results** — at the top how many differences, in which direction and how they
   break down by category. Below, the grouped tree with a colour per direction
   (missing here / missing there / different). Filter by name, tick the entries you
   care about and export: *Excel* for the whole report, *SQL* only for the selected
   differences.

The comparison runs on a separate thread: the window stays responsive even on large
schemas. Nothing is written to disk until you press *Export*.

## Usage (CLI, for the pipeline)

```sh
python -m diffdb.cli --list                                  # configured connections
python -m diffdb.cli SVI COL --out ./report                  # compare and write the outputs
python -m diffdb.cli SVI COL --fail-on-diff                  # exits 1 if they diverge
python -m diffdb.cli SVI COL --dry-run                       # only the differences, nothing on disk
python -m diffdb.cli SVI COL --json                          # the differences as JSON on stdout
python -m diffdb.cli sqlite:///a.db sqlite:///b.db           # two URLs on the fly, too
```

`--fail-on-diff` is what you need in CI: it fails the build if staging and
production have stopped resembling each other. `--dry-run` shows the same
differences but does not touch the filesystem — no script, no Excel, no snapshot,
no accepted rule — handy to see what a command would do before letting it do it for
real. `--json` replaces the textual summary with a JSON object on stdout (`env1`,
`env2`, `count`, `already_accepted`, `differences`, `written`) — stable
English keys, meant for another program to read, not to be read by eye. It combines
with `--dry-run` (`written` stays empty) and `--fail-on-diff` (the exit code does
not change).

## Build (portable executable)

```sh
pip install -r requirements-dev.txt
pyinstaller DiFFDB.spec
```

A single executable in `dist/`, with no installation and no Python: you copy it
wherever you want together with its `connections.json`. PyInstaller does not
cross-compile: the Windows exe is built on Windows, the Linux binary on Linux — the
pipeline in `.github/workflows/ci.yml` produces them for all three systems on every
tag, with SHA256 fingerprints and a real release (artifacts expire after 90 days).

### Signing

An unsigned executable is not just a warning: with SmartScreen most users stop, and
where there is AppLocker or WDAC it **does not start at all**. On macOS Gatekeeper
blocks it. On top of that PyInstaller binaries often end up in antivirus false
positives, precisely because malware uses them too.

CI signs if it finds the secrets configured, otherwise it produces the unsigned
binaries without failing. You need to configure:

| Where | What you need |
| --- | --- |
| Windows | A code-signing certificate. Since June 2023 the private key must live on hardware or on a cloud service: **a `.pfx` in a secret is no longer possible**. CI uses Azure Trusted Signing (`AZURE_SIGNING_*`); DigiCert KeyLocker and SSL.com eSigner have equivalent actions |
| macOS | Enrollment in the Apple Developer Program, a *Developer ID Application* certificate (`MACOS_CERTIFICATE_P12`), and `APPLE_ID` / `APPLE_TEAM_ID` / `APPLE_APP_PASSWORD` for notarization |

An EV certificate gives SmartScreen reputation immediately; an OV one builds it
over time. Timestamping is mandatory: without it, the signature stops being valid
when the certificate expires.

It is the only item in the whole project that **costs money** and not time: it has
to be decided up front, because without a certificate the signing step cannot even
be tried.

For the Windows icon you need an `.ico` (optional):

```sh
python -c "from PIL import Image; Image.open('images/logo.png').save('images/logo.ico')"
```

## Tests

```sh
python -m pytest tests/ --ignore=tests/integration    # unit, without a database
```

The tests create two real SQLite databases, compare them, **run** the generated
script and check the differences are gone. The window is instantiated headless
(`QT_QPA_PLATFORM=offscreen`), so the GUI is covered too.

### Quality checks

The same ones CI runs, which it runs **before** the tests: they are the fastest to
say no.

```sh
ruff check .                                   # style and known traps
python -m pytest tests/ --ignore=tests/integration --cov=diffdb --cov-fail-under=70
pip-audit --requirement requirements.txt       # known vulnerabilities in the dependencies
```

The coverage threshold sits below the current one: it is there to stop it from
dropping, not to chase a number. `pip-audit` on every push is how the first
vulnerability in a dependency of this project was found (and closed).

CI also produces an **SBOM** (CycloneDX) as an artifact: corporate security asks for
it before approving adoption, and generating it afterwards costs much more than now.

### Integration tests (on the real engines)

The unit tests run on SQLite: fast, but they say nothing about the other four
supported dialects. `tests/integration` repeats the same contract — **compare,
generate, run, re-compare, no difference** — talking to the real databases.

Each dialect is enabled with its own environment variable; without it, its tests
are **skipped** instead of failing, so you can run even a single dialect:

| Variable | Example |
| --- | --- |
| `DIFFDB_TEST_POSTGRESQL_URL` | `postgresql+psycopg2://postgres:pw@localhost:5432/postgres` |
| `DIFFDB_TEST_MYSQL_URL` | `mysql+pymysql://root:pw@localhost:3306/mysql` |
| `DIFFDB_TEST_MSSQL_URL` | `mssql+pymssql://sa:pw@localhost:1433/master` |
| `DIFFDB_TEST_ORACLE_URL` | `oracle+oracledb://system:pw@localhost:1521/?service_name=FREEPDB1` |

```sh
DIFFDB_TEST_POSTGRESQL_URL=... python -m pytest tests/integration -v
```

Locally a dialect without its variable is **skipped**. In CI it is not:
`DIFFDB_TEST_STRICT=1` makes a dialect that does not answer *fail*, because a green
job that ran nothing is worse than a red one — it looks like a confirmation.

The URL points to an **administrative** database: the two environments to compare
(`diffdb_test_svi` and `diffdb_test_col`) are created and destroyed by the tests —
separate databases, separate users on Oracle, where the schema *is* the user. No
preexisting data is touched. In CI the four dialects run on containers
(`.github/workflows/ci.yml`), Oracle in a separate job because it is the slowest to
start.

Known limitation: on SQLite, SQLAlchemy does not reflect the `UNIQUE` declared
inline on the column (only the table-level one). On the other databases this does
not happen.

Known limitation: on SQLite the reflection of **CHECK** constraints is unreliable —
the condition comes out with extra characters, and with more than one constraint
the names merge. DiFFDB does not read them on that dialect: the category stays empty
instead of comparing text the engine itself already mangled on read.

On SQL Server the limit is not in reading but in SQLAlchemy: the `pymssql` driver
does not implement CHECK reflection at all (`NotImplementedError`). DiFFDB reads its
constraints with a direct query on the system catalog (`sys.check_constraints`), as
it already does for sequences and synonyms where SQLAlchemy does not expose
something uniformly.

On PostgreSQL, MySQL, Oracle and SQL Server, CHECKs are compared by condition
(normalized), not by name: names are often auto-generated by the engine and change
from one environment to another even when the constraint is the same.

**Triggers** are not reflected by any dialect through SQLAlchemy (the Inspector does
not even have a method to list them): they are read with each engine's native way
to reconstruct the full CREATE TRIGGER — `pg_get_triggerdef` on PostgreSQL,
`DBMS_METADATA.GET_DDL` on Oracle, `sys.sql_modules` on SQL Server, `SHOW CREATE
TRIGGER` (one query per trigger) on MySQL. Comparison and alignment are always DROP
+ CREATE, never CREATE OR REPLACE: MySQL does not support it for triggers in any
version, and a single verifiable path on all engines beats an optimization that
varies from one to another.

On PostgreSQL and Oracle a trigger calls a separate function or procedure — the body
that matters is often there, not in the trigger text itself, which can stay
identical even if the logic changes. Hence the **stored procedures and functions**:
same principle as triggers (no reflection via SQLAlchemy, the full CREATE is
captured with `pg_get_functiondef`, `DBMS_METADATA.GET_DDL`, `sys.sql_modules`,
`SHOW CREATE PROCEDURE`/`FUNCTION`), same DROP + CREATE always, never CREATE OR
REPLACE. Standalone routines only: the members of an Oracle package are left out,
they are a separate category with an identity distinct from the package that
contains them. On PostgreSQL a function can be overloaded (same name, different
signature): the DROP also states the arguments, not just the name, or PostgreSQL
would not know which one to remove.

## Structure

| Path | Content |
| --- | --- |
| `pyproject.toml` | Installable package: `diffdb` and `diffdb-gui` commands |
| `main.py`, `diffdb/app.py` | GUI entry point |
| `diffdb/cli.py` | Command-line interface |
| `diffdb/rules.py` | Rules: filters and accepted differences |
| `diffdb/main_window.py` | Main window, tabs, connection management |
| `diffdb/diff_DB.py` | Comparison and generation of the SQL scripts |
| `diffdb/schema_snapshot.py` | Reading a database's structure |
| `diffdb/snapshot_io.py` | File snapshots: save, re-read, sources, fingerprint |
| `diffdb/audit.py` | Scripts' traceability header |
| `diffdb/urls.py` | Connection string: secrets, masking, policy |
| `diffdb/keystore.py` | Password in the operating-system keyring |
| `diffdb/log.py` | File logging, with passwords masked |
| `diffdb/i18n.py`, `diffdb/preferences.py` | Interface language and preferences |
| `diffdb/translations/`, `tools/traduzioni.py` | Translation catalogs and their regeneration |
| `diffdb/home_tab.py`, `diffdb/choose_tab.py` | Home screen and environment selection |
| `diffdb/results_tab.py` | Results tab: summary, tree, filter, selective export |
| `diffdb/report.py` | Writing Excel and scripts (used by GUI and CLI) |
| `diffdb/worker.py` | Comparison off the GUI thread |
| `diffdb/qt.py` | Single point of access to Qt and loading of the `.ui` files |
| `diffdb/theme.py` | Themes (tokens and palettes), font loading, runtime switching |
| `diffdb/widgets.py` | Hand-drawn widgets: gradient wordmark, TUI frames |
| `diffdb/connections.py`, `diffdb/paths.py` | Connections and paths (also from an executable) |
| `diffdb/config/dialectConfig.py` | SQL templates and capabilities of each dialect |
| `diffdb/utils/tableUtilities.py` | Comparison of two textual DDL files (standalone utility) |
| `diffdb/ui/`, `diffdb/styles/`, `diffdb/fonts/`, `diffdb/images/` | Qt Designer layouts, themes (`moderna.qss`/`retro.qss`), fonts, icons |

## Contributing

How to get started, what to run before a pull request and the project decisions
worth knowing: [CONTRIBUTING.md](CONTRIBUTING.md).

To report a vulnerability (**not** with a public issue), the minimum privileges
DiFFDB needs and what it really does with your databases: [SECURITY.md](SECURITY.md).

The changes version by version: [CHANGELOG.md](CHANGELOG.md).

## License

MIT (see `LICENSE`). The GUI uses **PySide6** (LGPL), not PyQt5: the latter is
GPL/commercial and distributing the executable would have required releasing
everything under GPL or buying a license.

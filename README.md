# LogComparator

LogComparator is a Windows desktop utility for loading TANGO logs from a local
log folder or from SSH/SCP (UAT), then building complete, readable
transaction flows from PTMS/SPDH and OPN/ISO audit streams.

The project directory is:

```text
C:\Users\j.arvanitis\Desktop\Tango\github\LogComparator
```

The default generated-log directory is:

```text
C:\Users\j.arvanitis\Desktop\Tango\LogComparator\Logs
```

The recommended import root is:

```text
C:\Users\j.arvanitis\Desktop\Tango\Import\<YYYY-MM-DD>
```

Generated files are organized under:

```text
C:\Users\j.arvanitis\Desktop\Tango\LogComparator\Logs\<BANK>\<YYYY-MM-DD>
```

## Main workflow

Running `main.py` without local audit arguments starts the GUI:

1. Open the main `LogComparator` application window.
   The window opens maximized.
2. Use **File > Import** for local files, or **File > SSH/SCP (UAT)** for UAT
   download.
3. Use **Tools > Export options** to choose `SPDH+ISO`, `ISO`, or `SPDH`,
   whether byte/data sections are included, and which audit blocks are exported.
4. The generated-file and byte/data options are also available in the options
   bar directly below the menu. `Open`, `Export`, and `Compare` are also
   available under the **Tools** menu.
5. For `Log folder`, use **File > Import** to select a local folder that
   contains the daily Tango log, PTMS audit, and selected bank OPN audit,
   compressed or uncompressed. No calendar is shown for this mode; the date is
   read from the folder's `tango.log...` filename. The selected path appears in
   the read-only `Log folder` field.
6. For `SSH/SCP (UAT)`, a separate calendar window opens automatically after
   the remote `tango.log*` list is loaded.
7. Select a highlighted date and a bank/acquirer in the SSH/SCP window, then
   press **OK**. Only the selected day's `tango.log*`, `audit.PTMS...`, and the
   OPN audit family mapped to that bank/acquirer are downloaded and extracted
   under `LogComparator\<YYYY-MM-DD>_UAT\<BANK>`. Select `All` to download and
   extract every OPN audit file for the date.
   Missing UAT source families are skipped: loading and export continue with
   the available files, even when PTMS, the selected bank OPN audit, or Tango
   is absent. The selected calendar date is used for loading transactions.
   If no UAT source files are found at all, the application reports that fact.
   Results contain only the data available in the downloaded files.
   The extracted folder path is written into the `Log folder` field.
   Progress is shown in the bottom-right progress bar of the main window while
   files are downloaded and extracted.
8. A specifically downloaded bank/acquirer is placed automatically in the main
   `Bank/Acquirer` combobox and its transaction list is loaded immediately,
   without requiring a second selection. With `All`, select one of the available
   banks in the main window. Optionally enter
   `TransUID`, `STAN`, `RRN`,
   `AuthCode`, `Sequence_Number`, `TransactionType`, `TID`, `MID`, `AMT`,
   `RC_SPDH`, or `RC_ISO` filters. The bank list
   contains all configured banks/acquirers, including `NEXI/COSMOTE`, once
   a source folder is selected.
   After a bank/acquirer is selected, the transaction list is populated.
9. Locate the daily Tango log, PTMS audit, and selected bank OPN audit.
10. Use the cached/extracted source files for parsing.
11. Parse all selected audit files as one chronological dataset.
12. Group records into complete transaction flows.
13. Press `Export` or use **File > Export** to create one `.log` file for
    every selected transaction/row that matches the filters. The main window
    remains open and reports completion or errors in the GUI.
14. Select one or more transaction rows and press `Open` to export them and open
    the generated `.log` files in Notepad++.
15. Select exactly two transaction rows to enable `Compare`; pressing it exports
    both logs and opens them in WinMerge.

Large audit files are scanned with memory mapping. The transaction-list loader
decodes only blocks containing a transaction ID and retains transaction metadata
instead of caching full multi-gigabyte file contents, substantially reducing RAM
usage and initial loading time.

The transaction list has separate `ISO possible problem` and
`SPDH possible problem` columns. When request and
response RRN values differ within the same OPN process, `ISO possible problem` displays
`differentRRN on the same transaction` and the entire row has a red background, overriding the green
approved highlighting. No RRN mismatch is reported when the RRNs match or either
side has no RRN available. Different processes are checked independently.
If an RRN occurs in different ISO transactions in the loaded audit dataset, all
affected rows show `RRN identical with other transaction` and turn red.
Reversal and void transactions are allowed to reuse an RRN and are excluded
from this duplicate check. Other transactions sharing that RRN with each other
are still flagged. The request/response RRN check also applies to reversals and voids.
RRN checks use ISO messages only; PTMS/SPDH RRNs are ignored for comparisons,
duplicate detection, and original-transaction lookup. SPDH original lookup uses
explicit original STAN or terminal/sequence references instead.
This checks all observed ISO RRNs, including response values, before bank and
table filters. Repeated occurrences within one transaction are not duplicates.
When both problems apply, both messages appear in the corresponding protocol column.

Diagnostic rules are separate from the GUI and core log parser:

- `iso_checks.py`: ISO field extraction and checks.
- `spdh_checks.py`: SPDH field extraction and checks.
- `tango_checks.py`: streaming Tango diagnostic detection and exact transaction matching.
- `transaction_checks.py`: RRN checks and orchestration of the two protocol columns.
- `diagnostic_common.py`: shared metadata, comparisons, original lookup, and row severity.

Additional ISO checks run on decoded OPN request/response records in both parsers.
They compare messages within the same transaction and OPN process, using known
ISO MTI pairs and STAN to distinguish multiple exchanges. Internal and SPDH
records do not participate in these ISO checks. Original STAN fields are kept
separate from the current STAN. Numeric padding is ignored for STAN, amount,
and currency comparisons; absent fields are not treated as different values.

| Finding in `ISO possible problem` | Highlight |
| --- | --- |
| `different STAN on the same transaction` | Red |
| `currency mismatch` | Red |
| `terminal or merchant mismatch` | Red |
| `unexpected response MTI` for a supported ISO pair | Red |
| `conflicting responses` with different response codes for the same MTI/STAN/process | Red |
| `original transaction mismatch` for a uniquely identified reversal/void original | Red |
| `invalid ISO message format (...)` for invalid decoded numeric DE4/11/49/90 or bitmap syntax | Red |
| `warning: amount mismatch (check partial approval/adjustment)` | Yellow |
| `warning: missing response code` for a supported response MTI | Yellow |
| Missing ISO request/response or original transaction | Yellow |
| Missing original reference or ambiguous pairing | Yellow |

Findings are combined within their protocol column. Red takes precedence over yellow,
and both take precedence over approved green. Declines alone are not flagged.
Original-transaction lookup uses DE90/original STAN when available, otherwise
original/current RRN, within the same OPN process across the loaded dataset.
DE90's timestamp is used to distinguish reused STANs when original DE7 is present.
Original MTI, explicit original RRN, terminal, merchant, and currency are compared
only when present. Partial reversals do not require equal amounts. Missing or
ambiguous originals are warnings because the loaded log may be incomplete.

Original-transaction mismatches include the exact field and the referenced/
observed values, for example `original_mti: referenced=0200, observed=0100`.
For NBG/OPENWAY (`OPNWAY4N*`), a `0420` void/reversal referencing original
MTI `0200` when the original request was `0100` is a yellow warning pending
verification of the NBG mapping. This finding alone does not make the row red.
Other original-reference mismatches and other banks retain their existing severity.
SPDH `Invoice_OriginTransSeqNo` is recognized as an original sequence reference.
Explicit ISO DE4/7/11/49/90 `hex<...>` values are decoded as packed decimal only
when they contain decimal digits with the exact expected byte width (and a zero
padding nibble for odd-width fields). Other hexadecimal encodings are skipped.

These checks do not implement a bank-specific wire decoder: raw hexadecimal
payloads, binary encodings, bitmap-to-payload consistency, and LLVAR/LLLVAR
length prefixes cannot be certified from decoded audit fields. Format checks
cover explicitly numbered decoded fields (including `DE011` and XML forms)
and logged hexadecimal/binary bitmaps. Integer renderings may omit leading
zeros. Proprietary MTI pairings are not guessed. Amount changes and missing
response codes remain warnings until bank-specific approval/required-field
rules are available.

ISO numbered fields are distinguished from deeper numbered EMV components;
an EMV component numbered 4 is not treated as ISO DE4.

SPDH checks use decoded PTMS field names, not ISO DE numbers. They check echoed
transmission number (`xchgId`), terminal/merchant, currency, STAN when available,
message class/subclass, and transaction code. Conflicting response codes for
the same observed message identity and malformed numeric transmission number,
transaction code, or response code are red findings. Missing response/code,
amount changes, and sequence/batch/shift differences are warnings. Sequence
changes can be legitimate resynchronization; retransmissions alone are not
errors. Original lookup additionally supports `originTransSeqNo` with terminal
identity. No raw SPDH decoding or mandatory optional-field assumptions are made.
The echo and resynchronization behavior is based on the
[ACI Standard POS Device Message Specifications R6.0v10](https://www.pors-sw.cz/stazeni/pos/instalace/terminaly/CSOB/aci_spdh_msg_specs_r6v10_0611.pdf).

Daily `tango.log` files (plain or gzip) are scanned in the background when the
transaction list loads. Explicit missing-field diagnostics include the field
name/number when logged; MAC verification failures, HSM failures, and communication
timeouts are also recognized. Only exact `transUId` references or the structured
Tango transaction-ID column are matched. Lines without a known transaction ID
are not assigned using timestamps or neighboring lines. OPN/ISO and PTMS/SPDH
messages go to their corresponding column. Unattributed protocol messages appear
in both columns explicitly labeled `Tango (protocol unspecified)`; this is one
shared diagnostic, not evidence of two separate failures. Optional missing fields
and communication timeouts are warnings. Repeated identical diagnostics are
deduplicated, and full raw log lines or payment payloads are not copied into the
columns. Changes to Tango log size/mtime invalidate the GUI row cache, and an
extracted log is preferred over its gzip copy.

Further candidate checks require bank/routing rules and sufficient flow evidence:
an ISO approval not delivered to the POS, a failed/missing compensating reversal,
or multiple approvals for the same business transaction. An RRN collision alone
does not prove duplicate charging.

Use **Help > About** to view the release tag, `git describe` build identifier,
exact Git hash, source state, and author (`IARV`). A value such as
`v1.0.21-3-gaadf381c63e5-dirty` identifies the nearest release, commit distance,
exact abbreviated commit, and uncommitted build changes. Versioning comes
entirely from annotated Git tags; there is no pre-commit version counter.
`build.json` is generated in the project root with `build_describe`,
`release_tag`, `git_hash`, and `git_dirty`. Source runs read this JSON.
PyInstaller embeds `build.json` using `--add-data "build.json;."`, so both
source runs and the executable read the same JSON format. The executable needs
no external metadata file or Git installation. `build.json` is ignored by Git. Without generated metadata,
source runs use an `untagged/development-unbuilt` fallback.

After every change, rebuild the executable from the project root with:

```powershell
.\.venv\Scripts\python.exe update_build_info.py
.\.venv\Scripts\pyinstaller.exe --onefile --name LogComparator --add-data "build.json;." main.py
```

The latest executable must always be stored inside the project at
`dist\LogComparator.exe`. The Desktop shortcut points to this fixed path,
so each rebuild updates the version it opens. Reopen any running instance
to use the rebuilt version.

Release creation follows `TangoWiresharkDisectors`: ordinary commits and branch
pushes do not create tags. Commit the source changes, then run explicitly:

```powershell
.\.venv\Scripts\python.exe create_release.py
```

The script fetches tags from `origin`, creates the next annotated
`vMAJOR.MINOR.PATCH` tag on HEAD and pushes only that tag. The first release is
`v1.0.0`; subsequent releases increment the highest patch version. An already
released commit reuses its annotated tag and retries its push. Tag collisions
are retried without force-pushing or overwriting remote tags. Source changes
must be committed; generated files under `build/` and `dist/` may remain modified.
The script refreshes `build.json` after publishing. It does not push the
branch or rebuild the executable. Use the build commands above afterwards.

To refresh metadata without creating or pushing a release tag, run
`.\.venv\Scripts\python.exe create_release.py --update-build-info`
or the existing `update_build_info.py` command. The executable retains its
embedded version until rebuilt. No automatic tagging workflow is used.

Progress, errors, and completion statistics are printed in the console.

## GUI controls

### Environment

The source is selected as follows:

- `Log folder`: use **File > Import** to select a local folder with the source files. The
  folder should contain one daily `tango.log...` file, one
  `audit.PTMS...` file, and one selected-bank `audit.OPN...` file for the
  target date. Place the files beforehand under
  `C:\Users\j.arvanitis\Desktop\Tango\Import\<YYYY-MM-DD>` and select that
  folder directly. Files may be plain text, `.gz`, or `.gzip`; compressed files
  are extracted there before transactions are scanned. No import copy is made.
- `SSH/SCP (UAT)`: use the SSH/SCP workflow. Selecting a calendar date downloads
  the selected bank's sources first into `LogComparator\<YYYY-MM-DD>_UAT\<BANK>`.
  Its transactions load immediately while a background worker downloads and
  extracts the remaining PTMS and OPN audit files for all banks on the same date
  into that folder. A separate status line shows background progress or errors.
  Completed files become available when switching banks; if another bank is
  selected during the download, its transaction list reloads when the worker finishes.
  The worker reuses the sources prepared for the selected bank and existing files
  for historical dates. Other files for today's date are refreshed. Downloads and
  extraction use a temporary directory so partial files are not scanned or exported.
  Changing the SSH date/bank selection or leaving the source cancels the previous
  background job after its current transfer. Selecting `All` downloads all sources
  in the initial download step.

Imported `.gz` and `.gzip` files are extracted inside the selected folder.
The scanner then reads the plain decompressed files, not the compressed files. During
export, source files are copied into the exported output `source` directory
before analysis. If both plain and compressed versions of the same source file
are present, the plain file is preferred to avoid duplicate audit blocks.
Numbered Tango filenames created during copying, such as
`tango.log.2026-07-08 1.gz`, are recognized as logs for `2026-07-08`; `.1`,
`_1`, and `-1` suffix variants are also accepted.

Numbered compressed PTMS parts are kept as separate inputs. For example,
`audit.PTMSMLN01.2026-07-08.gz` and
`audit.PTMSMLN01.2026-07-08.1.gz` are extracted separately and both
decompressed files are included in transaction analysis. The same applies to
the `.gzip` extension. If a gzip trailer is incomplete but valid log lines can
be recovered, the recovered content is retained and included in the analysis.

After a folder is extracted and validated successfully, the GUI displays a
**Folder loaded** confirmation with the selected path and the instruction
`Folder loaded. Please select the bank.` in both the dialog and status bar.

For `Log folder`, the main window shows a read-only folder path field. The
folder must contain one daily log set; if multiple `tango.log...` dates are
present, the run is rejected so the output date is not ambiguous.

If import validation fails, the **Import failed** dialog lists only the missing
source files. When a Tango log date is available, the expected PTMS and OPN
patterns include that exact date, for example `audit.PTMS*.*2026-07-13*`. The
validation also rejects an audit file that exists only for a different date.

For `SSH/SCP (UAT)`, the calendar opens automatically in a separate window when
the mode is selected. Choose a highlighted date and a bank/acquirer, then press
**OK**. The matching Tango log, PTMS audit, and selected bank's OPN audit family
are downloaded and extracted. Select `All` when every OPN audit for the date is
needed. A specific selected bank is populated automatically in the main window;
after `All`, choose a bank from the main Bank/Acquirer list. The extracted
`<YYYY-MM-DD>_UAT\<BANK>` or `<YYYY-MM-DD>_UAT\All` path is written into the
`Log folder` field. Use **File > SSH/SCP (UAT)** to choose another date or bank.

### Calendar

The calendar is used only for `SSH/SCP (UAT)` and opens in a separate window.
Only highlighted dates can be selected, and a Bank/Acquirer selection is
required before **OK** can continue. The download contains only:

- `tango.log*`
- `audit.PTMS...`
- the `audit.OPN...` family mapped to the selected bank/acquirer

Selecting `All` downloads and extracts all matching `audit.OPN...` files for
the selected date.

The files are extracted into `LogComparator\<YYYY-MM-DD>_UAT\<BANK>`. For a
past date, each file already present in that final folder is not downloaded
again; no separate download cache is created. Files for today's date are always
downloaded and extracted again so the folder contains the latest audit data.

### Bank/Acquirer

The bank controls the OPN audit process and the bank-filtering rules.
It is disabled until a source is available: import a folder with
**File > Import**, or select an SSH/SCP date first. The `TransUID`,
`STAN`, `RRN`, `AuthCode`, `Sequence_Number`, `TransactionType`, `TID`, `MID`,
`AMT`, `RC_SPDH`, and `RC_ISO` filter fields are disabled in the same
way.

The bank list shows all configured banks/acquirers once a source folder is
selected, including `NEXI/COSMOTE`. Missing bank audit files do not hide
choices from the list. Transactions still require matching source data.
Both Bank/Acquirer dropdowns show all choices without scrolling, including
the final `NEXI/COSMOTE` entry after `All` in the SSH/SCP dialog.

| GUI bank | OPN process |
| --- | --- |
| CASYS/STOPANSKA | OPNBISOCAS01 |
| CASYS/FIBANK | OPNBISOCAS01 |
| CASYS/RUBICON | OPNBISOCAS01 |
| AKTIF/BKT | OPNBISOBKT01 (acquirer ID 050) |
| AKTIF/BKTKOS | OPNBISOBKT01 (acquirer ID 065) |
| EURONET/OTP | OPNRENOTP01 family, for example OPNRENOTP01 and OPNRENOTP02 |
| NEXI/ALPHA | OPNBISOA01 |
| BORICA/PROCREDIT | OPNWAY4B01 |
| OPENWAY/NBG | OPNWAY4N01 |
| EUROBANK | OPNBISOE01 |
| NEXI/COSMOTE | OPNBISOC01 |

The displayed name is `NEXI/COSMOTE` (previously `COSMOTE/NEXI`). After
changing bank mappings in `log_config.py`, rebuild and open
`dist/LogComparator.exe` to use the updated names and bank list behavior.
For `NEXI/COSMOTE` transaction data, import a folder containing
`audit.OPNBISOC01.<date>` (with or without a `.log` suffix)
(or another numbered instance in the `OPNBISOC` family). Its acquirer ID
is `061`. Build using the project's `.venv\Scripts\pyinstaller.exe` so
the executable includes the installed `tkcalendar` dependency.

For banks other than `AKTIF/BKT` and `AKTIF/BKTKOS`, a transaction is retained
when it contains either the selected OPN process or a configured acquirer
identifier for that bank. This
prevents, for example, an OTP PTMS-only flow from being written into
`CASYS_FIBANK`.

`AKTIF/BKT` and `AKTIF/BKTKOS` are separate choices. Both use the
`OPNBISOBKT01` audit family, but transaction lists and exports distinguish
them by acquirer ID: `050` for `AKTIF/BKT` and `065` for `AKTIF/BKTKOS`. The shared process
name alone does not assign a transaction to either bank; a matching acquirer
ID is required.
For example, an `acqId=065` transaction in `audit.OPNBISOBKT01.<date>`
appears under `AKTIF/BKTKOS`, not under `AKTIF/BKT`. Transactions without
either matching acquirer ID are omitted from both lists.

### Transaction List

Selecting a bank/acquirer scans the active source folder and shows the matching
transactions in a table with:

- Date/Time
- transUid
- RRN
- STAN
- AuthCode
- Sequence_Number
- TransactionType
- TID
- MID
- AMT
- RC_SPDH
- RC_ISO

Rows have a green background when both `RC_SPDH` is `Approved(000)` and
`RC_ISO` is `Approved(00)`. A missing or non-approved response in either
column leaves the row with its normal background. Highlighting is preserved
when filtering, sorting, or reloading cached transactions.
Each RC column shows `Unknown` until a response containing a response code
is recorded for that protocol. Request defaults such as `000`/`00` and
internal messages are ignored. ISO requires an OPN `NETWORK-->TANGO`
response; SPDH requires a PTMS `TANGO-->NETWORK` response.

| RC_SPDH | RC_ISO | Row background |
| --- | --- | --- |
| Approved(000) | Approved(00) | Green |
| Unknown | Approved(00) | Normal |
| Approved(000) | Unknown | Normal |
| Unknown | Unknown | Normal |
| Any decline | Any value | Normal |
| Any value | Any decline | Normal |

`Unknown` applies independently to each protocol. A request containing a
default approval code does not establish that a response was received.

Click any column header to sort the displayed rows by that column. The table
supports selecting one or more rows. If rows are selected when `Export` runs,
only those selected transUIDs are exported. Explicit row selection takes
precedence over active text filters, so every selected TRX is written to a
separate `.log` file even when a text filter contains a partial value. While
the list is being built, the
bottom-right progress bar shows `Load transactions` with a determinate
percentage. Loaded rows are cached per bank/date/source-file fingerprint so
returning to the same selection is fast. The transaction-list scan uses an
in-memory fast path that extracts only audit blocks containing `transUId` and
skips uncorrelated no-`transUId` blocks. For speed, the list parser reads only
the fields needed by the table and filters, and ignores the heavy `Raw data`
payload while building rows. The same scan records audit block byte offsets,
so selected-row `Open`, `Export`, and `Compare` can seek directly to every
selected transaction without rescanning very large audit files. Full-day
exports still perform complete correlation for the generated `.log`.
Every explicitly selected TRX produces an output file even when the active
protocol or direction options exclude all of its audit blocks; in that case
the file still contains the available transaction summary and Tango lines.

When a bank/acquirer has more than one OPN audit file for the same date, all
files in the same numeric OPN family are loaded together. For example,
`EURONET/OTP` maps to the `OPNRENOTP01` family, so `audit.OPNRENOTP01...`,
`audit.OPNRENOTP02...`, and other matching `OPNRENOTP##` files are included when
they exist.

`Open` exports the selected row(s) first, then opens the generated `.log` files
with Notepad++. Multiple selected rows are exported to separate files and all
of them are passed to the same Notepad++ launch. `Compare` is enabled only when
exactly two rows are selected; it
exports both logs and opens them in WinMerge. The program looks for
`notepad++.exe` and `WinMergeU.exe` in `PATH` and in the standard 32-bit/64-bit
Program Files install folders. Selected-row `Open` and `Compare` use a targeted
memory-mapped export path that searches directly for the selected `transUId`
values. It decodes only matching audit blocks instead of loading multi-GB audit
files into RAM, so comparing two selected rows remains responsive.
For a selected-row export, the first targeted audit lookup temporarily caches
only that transaction's matching blocks. File generation reuses those blocks
instead of scanning the same multi-GB audits a second time, and matching Tango
lines are collected with streaming I/O.
The initial transaction-list scan also records the byte offsets of each block.
Later single-row exports seek directly to those offsets, avoiding even the
first full-file search when the list has already been loaded.

The `Timezone` combo changes only how the `Date/Time` column is displayed. The
source timestamp is treated as UTC; choosing `UTC+1`, `UTC+2`, `UTC+3`,
`UTC-1`, `UTC-2`, or `UTC-3` shifts the displayed value without changing the
raw parsed data, filters, or exported logs.

The TransUID, RRN, STAN, AuthCode, Sequence_Number, TransactionType, TID, MID,
AMT, RC_SPDH, and RC_ISO fields also act as live filters for the transaction
table. `Sequence_Number` is read from audit values such as
`[0x1C68] Sequence_Number : asc<0010090800>`.
`TransactionType` is resolved from the current TANGO/ISO MTI and displays
`Unknown` when the MTI is missing or unrecognized. TANGO `4820` is
`DCC Inquiry`, including BKT/BKTKOS flows whose ISO message is `0800`/`0810`.
Processing code `910000` alone does not identify DCC and must not override
LOGON/ECHO evidence. Explicit message
descriptions distinguish `LOGON` and `ECHO`; configured echo MTIs are
also recognized. An otherwise unclassified `0800` is
`Network_Management_Request`, never automatically `Logon`.
Processing codes such as `000000` are not transaction names and are never
displayed as synthetic `ProcessingCode_...` types. The current MTI takes priority
over `originMti`/`tgOriginMti`; for example, a `4554` referencing an original
`4530` is displayed as `Purchase_Void`, and `4581` is displayed as
`Purchase_Void_Reversal`.
Double-clicking a transaction row exports its flow and opens the generated log
in Notepad++. Right-clicking a row opens a context menu with `Open`, `Export`,
and `Compare`; `Compare` is enabled only when exactly two rows are selected.
Text filters use a short 400 ms debounce. Typing another character cancels the
pending refresh, so a large transaction table is rebuilt only after input
pauses instead of once for every keystroke.
All transaction text-filter controls are grouped inside a bordered `Filters`
area. The separate `Time range` area remains on the upper source row.

Before the `TransUID` filter, permanently visible `From` and `To` controls show
the year, month, day, hour, minute, and second of the minimum and maximum loaded
timestamps. The date is selected with a GUI calendar and `HH:MM:SS` with
dropdowns. The selected inclusive range acts as a live filter and follows the
timezone selected in the GUI.
After loading, the range initially covers the complete log day, from
`00:00:00` through `23:59:59`, rather than only the first and last transaction
times.
The `Log folder` field expands into the available horizontal space. The
`From`, `To`, and `Timezone` controls are grouped in a separate bordered
`Time range` area that aligns with the right side of the upper row.
`Log folder` and `Bank/Acquirer` are grouped together in a bordered `Data`
area beside `Time range`.
The short `From` and `To` labels appear inline immediately before their date
and `HH:MM:SS` controls rather than above them.
Changing `Timezone` converts the visible `From` and `To` values along with the
table's `Date/Time` values. For example, changing from `UTC` to `UTC+3` adds
three hours to both displayed bounds while preserving the same absolute range.
On initial loading, transaction timestamps are converted to the active
timezone first. `From` is then set to `00:00:00` on the first resulting local
date and `To` to `23:59:59` on the last resulting local date.

### TransUID

The TransUID, STAN, RRN, AuthCode, Sequence_Number, TransactionType, TID, MID,
AMT, RC_SPDH, and RC_ISO fields are optional:

For ISO audit records, `MID` also recognizes `cardAcceptorId`, while `AMT`
prioritizes `transactionAmt` over auxiliary nested amount fields.

- Empty fields: export every transaction that matches the selected bank.
- Filled fields: export only transactions matching all filled values.

Use **View > Columns / Filters...** to choose which transaction fields are
visible. Each checked item appears both as a table column and as a filter. When
an item is unchecked, its column and filter are hidden and any value in that
filter is cleared.

A targeted run does not create `NO_TRANSUID.log` and does not delete or
rewrite unrelated existing transaction files.

### Generated Files

The generated file type is selected from **Tools > Export options** or
from the `Generated files` controls below the menu:

- `SPDH+ISO`: write both PTMS/SPDH and OPN/ISO audit blocks.
- `ISO`: write only OPN/ISO audit blocks.
- `SPDH`: write only PTMS/SPDH audit blocks.

When a protocol is selected, only matching audit blocks are written inside each
exported transaction file. The unassigned `NO_TRANSUID.log` file is not produced
for protocol-filtered runs.

### Byte/Data

The same **Tools > Export options** menu and the `Byte/Data` checkbox
below the menu control verbose payload sections:

- `Include byte/data`: keep the full detailed data sections in full
  transaction logs.
- `Exclude byte/data`: remove `Raw data (hex):` and `Bus data:` sections from
  exported logs.

`Byte/Data` starts disabled when the GUI opens and can be enabled before export.

When `Exclude byte/data` is selected, `Raw data (hex):` and `Bus data:` are
removed from the exported `.log`.

The audit block checkboxes beside `Byte/Data` control which block categories are
written into the exported `.log`:

- `Tango Internal`: internal TANGO request/response audit blocks.
- `Tango->Network`: outgoing external audit blocks.
- `Network->Tango`: incoming external audit blocks.

`Tango Internal` starts disabled when the GUI opens. `Tango->Network` and
`Network->Tango` start enabled.

## Source cache

For `SSH/SCP (UAT)`, source files are downloaded and extracted under:

```text
LogComparator\<YYYY-MM-DD>_UAT\<BANK>
```

Exported transaction logs for UAT are written under:

```text
LogComparator\<BANK>\<YYYY-MM-DD>
```

For both `Log folder` and `SSH/SCP (UAT)`, source files are copied under:

```text
LogComparator\<BANK>\<YYYY-MM-DD>\source
```

The bank name is made Windows-safe, so `CASYS/FIBANK` becomes
`CASYS_FIBANK`.

For `Log folder`, if a basename already exists locally, the copy is skipped:

```text
Using existing file: ...
```

If a `.gz` or `.gzip` file imported through `Log folder` already has a
decompressed sibling, decompression is also skipped:

```text
Using existing decompressed file: ...
```

The `SSH/SCP (UAT)` calendar skips files already present in the final folder for
past date/bank combinations. Today's files are always downloaded and extracted
again because the active audit files can still change during the day.

## Transaction correlation

The primary correlation key is `transUId`. All blocks with the same value are
grouped into the same flow, including requests, responses, callbacks, and
internal actions.

For blocks without `transUId`, the parser can correlate using:

- RRN
- STAN/audit number
- `trmUId`
- `msgUId`
- A nearby timestamp within the configured correlation window

Uncorrelated system records such as logon/heartbeat events are written to
`NO_TRANSUID.log` during a full run.

Audit boundaries support:

- `RP date time`
- `RP date time GMT`
- `SP date time`
- `SP date time GMT`

The complete audit timestamp, including milliseconds, is used to sort PTMS and
OPN blocks together. Input-file order does not control output order.

## Output layout

Example:

```text
LogComparator\CASYS_FIBANK\
    2026-06-19\
        <transUId>.log
        NO_TRANSUID.log
        source\
            tango.log.2026-06-19
            audit.PTMSPMLN01.2026-06-19
            audit.OPNBISOCAS01.2026-06-19
```

Every normal transaction produces one file:

```text
<transUId>.log
```

Blocks without a `transUId` are written to `NO_TRANSUID.log` during a full run.
When a transaction is regenerated, old filename variants for the same
`transUId` are removed.

## Filename format

```text
<transUId>.log
NO_TRANSUID.log
```

Rules:

- Full transaction logs are named only by the TANGO `transUId`.
- Records with no `transUId` go to `NO_TRANSUID.log`.
- The selected export type controls which audit blocks are written inside the
  `.log`; it does not change the filename.
- Windows-unsafe characters are normalized.

Example:

```text
36178713733611102100139.log
```

## Full transaction log

The exported transaction log begins with a structured transaction summary:

```text
###############################################################################
TRANSACTION SUMMARY
###############################################################################
transUId        : 36178713733611102100139
RRN             : 000537001063
Date/Time       : 2026-06-19 08:25:37.320

TID                  : PS060063
MID                  : 123456789012345
AMT                  : 1000(978)
Acquirer             : 065
MTI                  : 4530

Internal result Code : 2105
RC_SPDH              : 050
RC_ISO               : 05 (Do Not Honor)

Status               : DECLINED
###############################################################################
```

RRN is omitted from the header when unavailable.

The transaction summary is followed by `TRANSACTION FLOW`, then:

1. Every raw daily `tango.log` line containing the exact `transUId`.
2. Every correlated PTMS and OPN audit block.
3. Internal and external REQUEST/RESPONSE actions.
4. Complete `Audit data` and `Bus data`.

The full log is the detailed diagnostic artifact and is the only generated
transaction file.

### Diagram labels

The diagram uses:

- `[SPDH]` for PTMS network directions.
- `[ISO]` for OPN network directions.
- `[INTERNAL]` for internal REQUEST actions.

External protocol boundaries have no indentation. Internal actions use eight
spaces. No arrow characters are written.

Example:

```text
[SPDH] NETWORK -> TANGO
	[INTERNAL] 6034  VERIFY MAC
	[INTERNAL] 4530  APPLICATION REQUEST FOR PROCESSING
[ISO] TANGO -> NETWORK
[ISO] NETWORK -> TANGO  Approved(00)
	[INTERNAL] 6022  GENERATE MAC
	[INTERNAL] 4530  CALL DATA LOGGER
[SPDH] TANGO -> NETWORK  Sequence error resync(899)
```

Each real internal REQUEST occurrence is retained, including repeated identical
actions. Only an unchanged repeated `[ISO] TANGO -> NETWORK` state is
suppressed. Its surrounding internal actions are not removed.

RC text is added only to external blocks whose `Flow type` is `response`:

- OPN response: ISO description/value.
- PTMS response: SPDH description/value.

Some transactions legitimately contain only SPDH. For example, a validation
failure may stop internally before any OPN/ISO request is sent.

## TANGO transaction and reversal MTIs

Business TANGO MTIs take priority over generic ISO/internal-action names when
building the transaction summary.

Dots shown in database displays are removed in audit values:
`4.530` is parsed as `4530`.

| Transaction MTI | Reversal MTI | Description |
| --- | --- | --- |
| 4013 | 8707 | Pre-auth Request |
| 4530 | 4546 | Purchase |
| 4531 | 4547 | Cash Advance |
| 4533 | 4549 | Purchase with Cashback |
| 4534 | 5251 | Refund |
| 4538 | 4558 | Financial Purchase Advice |
| 4554 | 4581 | Purchase Void |
| 4555 | 4582 | Refund Void |
| 4557 | 4583 | Purchase with Cashback Void |
| 4559 | 4584 | Cash Advance Void |
| 5109 | 5259 | Debit Adjustment |
| 5110 | 5260 | Credit Adjustment |
| 8706 | 8705 | Pre-auth Completion |
| 8760 | 8763 | Pre-auth Void |

Reversal descriptions use the original description plus `_Reversal`, for
example `4546 -> Purchase_Reversal`.

Other supported internal actions include:

- `6001 -> Generate_Key`
- `6034 -> Verify_MAC_Msg_From_PoS`
- `6022 -> Generate_MAC_To_POS`
- `4842 -> Call_Data_Logger`

## ISO MTIs

Decoded BICISO network MTIs are read from fields such as:

```text
msgId : asc<0200>
```

The ISO table covers authorization, financial, reversal, batch/settlement,
network management, administrative/security, file/parameter management, and
configured proprietary MTIs.

When no business TANGO MTI exists, the ISO MTI description is used, for example:

- `0200 -> Financial_Request`
- `0210 -> Financial_Response`
- `0400 -> Reversal_Request`
- `0420 -> Reversal_Advice`
- `0800 -> Network_Management_Request` (unless operation details identify DCC, Logon or Echo)

## Response codes

### ISO response code

The ISO RC is taken only from an OPN external response block:

```text
Process name: OPN...
Flow dir: NETWORK-->TANGO
Flow type: response
responseCode: asc<xx>
```

### SPDH response code

The SPDH RC is taken only from a PTMS external response block:

```text
Process name: PTMS...
Flow dir: TANGO-->NETWORK
Flow type: response
responseCode: asc<xxx>
```

SPDH descriptions come from the supplied 123-code TANGO `RC_CODES` table.
Duplicate source entries `950` through `954` use their final definitions,
matching Lua table assignment behavior.

## Local analysis mode

Analyze one or more existing audit files without SSH or the GUI:

```powershell
.\.venv\Scripts\python.exe .\main.py audit.file1 audit.file2 -o C:\path\to\output
```

Prepend matching lines from an existing Tango log:

```powershell
.\.venv\Scripts\python.exe .\main.py audit.file1 audit.file2 --tango-log C:\path\to\tango.log -o C:\path\to\output
```

Export only one protocol block type in local mode:

```powershell
.\.venv\Scripts\python.exe .\main.py audit.file1 audit.file2 --protocol SPDH+ISO -o C:\path\to\output
```

Remove verbose byte/data sections in local mode:

```powershell
.\.venv\Scripts\python.exe .\main.py audit.file1 audit.file2 --exclude-byte-data -o C:\path\to\output
```

Filter by STAN, RRN, or AuthCode in local mode:

```powershell
.\.venv\Scripts\python.exe .\main.py audit.file1 audit.file2 --stan 123456 --rrn 000358000879 --authcode A1B2C3 -o C:\path\to\output
```

Filter by Sequence_Number in local mode:

```powershell
.\.venv\Scripts\python.exe .\main.py audit.file1 audit.file2 --sequence-number 0010090800 -o C:\path\to\output
```

Without positional audit files, `main.py` opens the GUI.

## Installation

Requirements:

- Windows with Python 3.
- Python packages from `requirements.txt`.
- Notepad++ installed. It is required for the `Open` action.
- WinMerge installed. It is required for the `Compare` action.
- The Notepad++ **EnhanceAnyLexer** plugin installed. It is required for the
  supplied color highlighting rules.

Additional `SSH/SCP (UAT)` requirements:

- Windows OpenSSH `ssh` and `scp` on `PATH`.
- Network access to the configured server.
- Permission to run the required remote commands through `sudo`.

Setup:

```powershell
cd C:\Users\j.arvanitis\Desktop\Tango\github\LogComparator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Configuration

The following values are configured near the top of `log_core.py`:

- SSH host, port, user, and timeout.
- Remote Tango log and audit directories.
- Local output root.
- Bank-to-OPN mappings.
- Bank acquirer identifiers.
- TANGO/ISO MTI descriptions.
- ISO/SPDH response-code descriptions.
- Correlation window.

Security note: the sudo password is currently stored as plain text in
`log_core.py`. Keep the repository and its copies appropriately protected.

## Notepad++ EnhanceAnyLexer

Colored log highlighting requires the **EnhanceAnyLexer** Notepad++ plugin.
The exported log files remain plain text and can be opened without the plugin,
but the blue and red highlighting described below will not be available.

### Plugin installation

Use a Notepad++ version supported by EnhanceAnyLexer. The plugin architecture
must match the installed Notepad++ architecture: use the 64-bit plugin with
64-bit Notepad++ and the 32-bit plugin with 32-bit Notepad++. Installing through
Plugins Admin is recommended because it selects a compatible plugin build. If
EnhanceAnyLexer does not appear in Plugins Admin, update Notepad++ to a current
supported release first.

1. Open Notepad++.
2. Select **Plugins > Plugins Admin**.
3. Search for **EnhanceAnyLexer** in the **Available** tab.
4. Select the plugin and press **Install**.
5. Allow Notepad++ to restart when requested.

### Color configuration

The repository includes the ready-to-use configuration file:

```text
EnhanceAnyLexerConfig.ini
```

Copy it to the EnhanceAnyLexer configuration directory for the current Windows
user, replacing the existing file when present:

```text
C:\Users\j.arvanitis\AppData\Roaming\Notepad++\plugins\config\EnhanceAnyLexer\EnhanceAnyLexerConfig.ini
```

The equivalent generic path is:

```text
%APPDATA%\Notepad++\plugins\config\EnhanceAnyLexer\EnhanceAnyLexerConfig.ini
```

After copying the file:

1. Restart Notepad++ completely.
2. Open an exported `.log` file.
3. Ensure its Notepad++ language is **Normal text**, because the rules are under
   the `[normal text]` section of the configuration.
4. If an already-open log does not refresh, close and reopen its tab or switch
   to another tab and back.

When updating the configuration later, copy the repository version to the same
directory again and restart Notepad++.

### Configured colors

It uses exactly two BGR color values because `use_rgb_format=0`:

- `0xFF0000`: blue.
- `0x0000FF`: red.

Blue highlighting covers:

- Field names `responseCode`, `resultCode`,
  `retrievalReferenceNumber`, and `MTI`.
- The entire header line `RRN: <value>`.
- The entire line containing `transUId`.
- The entire decoded line `responseCode : asc<xx>` by default.

Red highlighting overrides blue for:

- Every mapped ISO/SPDH decline response code.
- Declined `Internal result Code`, `RC_SPDH`, and `RC_ISO` summary lines.
- Full decoded decline lines such as `responseCode : asc<96>`.
- External ISO lines whose final RC is not `00`.
- External SPDH lines whose final RC is not `000`.
- `resultCode=3919`.
- `resultCode=3090`.

Approved response codes `00`, `000`, and `953` are excluded from the red
decline rule.

EnhanceAnyLexer supports only text foreground recoloring. It cannot make only
the red regex matches bold. Selective red+bold styling requires a different
lexer or a scripting plugin.

After changing the config, reactivate the Notepad++ buffer or restart Notepad++
if highlighting does not refresh.

## Troubleshooting

### A selected transaction has only PTMS/SPDH

The transaction may have failed validation before reaching OPN. Check the Tango
lines for a critical result code and confirm whether an OPN network block exists.

### A Financial_Response appears without OPN

Confirm bank filtering. A PTMS transaction can belong to another route, such as
`acqId=063 / OPNRENOTP01`, and must not be included in a CASYS/FIBANK run.

### Unknown_MTI

The flow contains no MTI present in the business TANGO or ISO mapping. Internal
security/action MTIs are not automatically assigned an unrelated business type.

### Old filenames remain

Run the analysis again for the same transaction. Exported variants for that
`transUId` are cleaned when the transaction is regenerated. Targeted runs do
not remove unrelated transactions.

### Ctrl+C

The calendar periodically returns control to Python so Ctrl+C can be processed.
SSH/SCP subprocesses are also bounded by configured timeouts.

### No new copy occurs in Log folder mode

The `Log folder` source cache is active. Remove the corresponding file from the
bank and date-specific `source` directory when a fresh log-folder copy is
required. Calendar selection in `SSH/SCP (UAT)` always downloads and extracts
the selected date again.

## Project files

| File | Purpose |
| --- | --- |
| `main.py` | Small CLI/GUI entrypoint |
| `gui_app.py` | Tkinter window layout, menus, filters, transaction table, and user actions |
| `gui_services.py` | GUI service helpers for SSH/SCP source download, external tool discovery/focus, and GUI export orchestration |
| `log_config.py` | Application constants, bank/acquirer mappings, protocol choices, MTI names, and ISO/SPDH response-code descriptions |
| `log_core.py` | Parsing, transaction correlation, log export, local source handling, and response-code lookup logic |
| `requirements.txt` | Python dependency pins |
| `README.md` | Project behavior and operational documentation |
| `AGENTS.md` | Repository-specific development instructions |

All transaction labels (including Purchase, Refund, Reversal, LOGON, ECHO
and DCC Inquiry) include the observed external audit flow phases per protocol:
`SPDHreq` / `SPDHresp` for SPDH (PTMS) request / response and
`ISOreq` / `ISOresp` for ISO (OPN) request / response.
For example, a purchase with both protocols and both phases is
`Purchase (SPDHreq-ISOreq-ISOresp-SPDHresp)`; an ISO request alone is `Purchase (ISOreq)`.
Only observed phases are included, grouped in parentheses in their first occurrence
order in the exported file (timestamp, then source block order). Repeated phases
appear once. Internal action
responses do not add a response phase.
Existing trailing `_Request`/`_Response` in MTI names is replaced by the
observed phase to avoid duplicate labels. If no external flow phase is known,
only the operation name is shown.

For OPN ISO `0800`/`0810` blocks, DE070 (Network Management Information
Code) identifies `001` as LOGON and `301` as ECHO. This field takes priority
over generic/internal MTI descriptions, including `4820`. Both the transaction
list and export parsers read numbered `70.` audit fields, `DE070`/`DE70`,
and named network-management code fields (audit or XML). Missing or unknown
DE070 values do not automatically imply LOGON or ECHO. Request/response
suffixes still come from observed external audit blocks.
Reference: [jPOS LogonManager](https://fw.jpos.org/docs/tutorial/logon-manager/).

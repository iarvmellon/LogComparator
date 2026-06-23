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
C:\Users\j.arvanitis\Desktop\Tango\Logs\LogComparator
```

## Main workflow

Running `main.py` without local audit arguments starts the GUI:

1. Open the main `LogComparator` application window.
   The window opens maximized.
2. Use **Tools > Import** for local files, or **File > SSH/SCP (UAT)** for UAT
   download.
3. Use **File > Export options** to choose `SPDH+ISO`, `ISO`, or `SPDH`,
   whether byte/data sections are included, and which audit blocks are exported.
4. The generated-file and byte/data options are also available in the options
   bar directly below the menu. `Open`, `Export`, and `Compare` are also
   available under the **Tools** menu.
5. For `Log folder`, use **Tools > Import** to select a local folder that
   contains the daily Tango log, PTMS audit, and selected bank OPN audit,
   compressed or uncompressed. No calendar is shown for this mode; the date is
   read from the folder's `tango.log...` filename. The selected path appears in
   the read-only `Log folder` field.
6. For `SSH/SCP (UAT)`, a separate calendar window opens automatically after
   the remote `tango.log*` list is loaded.
7. Select a date in the SSH/SCP calendar when using SSH/SCP mode. The selected
   day's `tango.log*`, `audit.PTMS...`, and all `audit.OPN...` files are
   downloaded and extracted immediately under `LogComparator\<YYYY-MM-DD>_UAT`.
   The extracted folder path is written into the `Log folder` field.
   Progress is shown in the bottom-right progress bar of the main window while
   files are downloaded and extracted.
8. Select a bank/acquirer, and optionally enter `TransUID`, `STAN`, `RRN`,
   `AuthCode`, `responseCodeSPDH`, or `responseCodeISO` filters. The bank list
   contains only choices matching the available `audit.OPN...` files in the
   selected/extracted folder.
   After a bank/acquirer is selected, the transaction list is populated.
9. Locate the daily Tango log, PTMS audit, and selected bank OPN audit.
10. Use the cached/extracted source files for parsing.
11. Parse all selected audit files as one chronological dataset.
12. Group records into complete transaction flows.
13. Press `Export` or use **Tools > Export** to create one `.log` file for
    every selected transaction/row that matches the filters. The main window
    remains open and reports completion or errors in the GUI.
14. Select one or more transaction rows and press `Open` to export them and open
    the generated `.log` files in Notepad++.
15. Select exactly two transaction rows to enable `Compare`; pressing it exports
    both logs and opens them in WinMerge.

Use **Help > About** to view the program version and author (`IARV`).

Progress, errors, and completion statistics are printed in the console.

## GUI controls

### Environment

The source is selected as follows:

- `Log folder`: use **Tools > Import** to select a local folder with the source files. The
  folder should contain one daily `tango.log...` file, one
  `audit.PTMSPMLN01...` file, and one selected-bank `audit.OPN...` file for the
  target date. Files may be plain text or `.gz`.
- `SSH/SCP (UAT)`: use the SSH/SCP workflow. Selecting a calendar date downloads
  all UAT source files for that day into `LogComparator\<YYYY-MM-DD>_UAT`.

Log folder files are copied into the exported output `source` directory before
analysis. The original log folder is not modified. If both plain and `.gz`
versions of the same source file are present, the plain file is preferred to
avoid duplicate audit blocks.

For `Log folder`, the main window shows a read-only folder path field. The
folder must contain one daily log set; if multiple `tango.log...` dates are
present, the run is rejected so the output date is not ambiguous.

For `SSH/SCP (UAT)`, the calendar opens automatically in a separate window when
the mode is selected. After choosing a highlighted date, all matching UAT source
files are downloaded and extracted, then the selected date is shown in the main
window and the extracted `<YYYY-MM-DD>_UAT` path is written into the
`Log folder` field. Use **File > SSH/SCP (UAT)** to choose another date.

### Calendar

The calendar is used only for `SSH/SCP (UAT)` and opens in a separate window.
Only highlighted dates can be selected. Selecting a date downloads:

- `tango.log*`
- `audit.PTMSPMLN01...`
- all `audit.OPN...` files

The files are extracted into `LogComparator\<YYYY-MM-DD>_UAT`.

### Bank/Acquirer

The bank controls the OPN audit process and the bank-filtering rules.
It is disabled until a source is available: import a folder with
**Tools > Import**, or select an SSH/SCP date first. The `TransUID`,
`STAN`, `RRN`, `AuthCode`, `responseCodeSPDH`, and `responseCodeISO` filter
fields are disabled in the same way.

The bank list is built from the `audit.OPN...` files found in the active source
folder. For example, a folder containing `audit.OPNBISOBKT01...` enables
`AKTIF/BKT`; a folder containing `audit.OPNBISOCAS01...` enables the CASYS
bank/acquirer choices mapped to that audit process.

| GUI bank | OPN process |
| --- | --- |
| CASYS/STOPANSKA | OPNBISOCAS01 |
| CASYS/FIBANK | OPNBISOCAS01 |
| CASYS/RUBICON | OPNBISOCAS01 |
| AKTIF/BKT | OPNBISOBKT01 |
| EURONET/OTP | OPNRENOTP01 |
| NEXI/ALPHA | OPNBISOA01 |
| BORICA/PROCREDIT | OPNWAY4B01 |
| NBG | OPNWAY4N01 |
| EUROBANK | OPNBISOE01 |
| COSMOTE/NEXI | OPNBISOC01 |

Filtering is strict. A transaction is retained when it contains either the
selected OPN process or a configured acquirer identifier for that bank. This
prevents, for example, an OTP PTMS-only flow from being written into
`CASYS_FIBANK`.

### Transaction List

Selecting a bank/acquirer scans the active source folder and shows the matching
transactions in a table with:

- Date/Time
- transUid
- RRN
- STAN
- AuthCode
- TransactionType
- responseCodeSPDH
- responseCodeISO

Click any column header to sort the displayed rows by that column. The table
supports selecting one or more rows. If rows are selected when `Export` runs,
only those selected transUIDs are exported. While the list is being built, the
bottom-right progress bar shows `Load transactions` with a determinate
percentage. Loaded rows are cached per bank/date/source-file fingerprint so
returning to the same selection is fast. The transaction-list scan uses an
in-memory fast path and skips uncorrelated no-`transUId` blocks; the full export
still performs complete correlation for the generated `.log`.

`Open` exports the selected row(s) first, then opens the generated `.log` files
with Notepad++. `Compare` is enabled only when exactly two rows are selected; it
exports both logs and opens them in WinMerge. The program looks for
`notepad++.exe` and `WinMergeU.exe` in `PATH` and in the standard 32-bit/64-bit
Program Files install folders. Selected-row `Open` and `Compare` use a targeted
export path that extracts only the audit blocks containing the selected
`transUId` values, so they are much faster than exporting a full day.

The TransUID, RRN, STAN, AuthCode, responseCodeSPDH, and responseCodeISO fields
also act as live filters for the transaction table.

### TransUID

The TransUID, STAN, RRN, AuthCode, responseCodeSPDH, and responseCodeISO fields
are optional:

- Empty fields: export every transaction that matches the selected bank.
- Filled fields: export only transactions matching all filled values.

A targeted run does not create `NO_TRANSUID.log` and does not delete or
rewrite unrelated existing transaction files.

### Generated Files

The generated file type is selected from **File > Export options** or
from the `Generated files` controls below the menu:

- `SPDH+ISO`: write both PTMS/SPDH and OPN/ISO audit blocks.
- `ISO`: write only OPN/ISO audit blocks.
- `SPDH`: write only PTMS/SPDH audit blocks.

When a protocol is selected, only matching audit blocks are written inside each
exported transaction file. The unassigned `NO_TRANSUID.log` file is not produced
for protocol-filtered runs.

### Byte/Data

The same **File > Export options** menu and the `Byte/Data` checkbox
below the menu control verbose payload sections:

- `Include byte/data`: keep the full detailed data sections in full
  transaction logs.
- `Exclude byte/data`: remove `Raw data (hex):` and `Bus data:` sections from
  exported logs.

When `Exclude byte/data` is selected, `Raw data (hex):` and `Bus data:` are
removed from the exported `.log`.

The audit block checkboxes beside `Byte/Data` control which block categories are
written into the exported `.log`:

- `Tango Internal`: internal TANGO request/response audit blocks.
- `Tango->Network`: outgoing external audit blocks.
- `Network->Tango`: incoming external audit blocks.

## Source cache

For `SSH/SCP (UAT)`, source files are downloaded and extracted under:

```text
LogComparator\<YYYY-MM-DD>_UAT
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

For both modes, if a basename already exists locally, the download/copy is
skipped:

```text
Using existing file: ...
```

If a `.gz` file already has a decompressed sibling, decompression is also
skipped:

```text
Using existing decompressed file: ...
```

The cache is intentionally based on filename existence. Delete a cached source
file manually when a fresh remote copy is required.

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

Terminal        : PS060063
Acquirer        : 065
MTI             : 4530

Result Code     : 2105
Response Code   : 050
Network RC      : 05 (Do Not Honor)

Status          : DECLINED
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
- `0800 -> Network_Management_Request_(...)`

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

The SPDH RC is taken only from the final PTMS external response block:

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

Without positional audit files, `main.py` opens the GUI.

## Installation

Requirements:

- Windows with Python 3.
- Python packages from `requirements.txt`.

Additional `SSH/SCP (UAT)` requirements:

- Windows OpenSSH `ssh` and `scp` on `PATH`.
- Network access to the configured server.
- Permission to run the required remote commands through `sudo`.

Optional GUI integration tools:

- Notepad++ for the `Open` button.
- WinMerge for the `Compare` button.

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
- Declined `Result Code`, `Response Code`, and `Network RC` summary lines.
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

### No new download or copy occurs

The source cache is active. Remove the corresponding file from the bank and
date-specific `source` directory when a fresh SSH/SCP download or log-folder
copy is required.

## Project files

| File | Purpose |
| --- | --- |
| `main.py` | Small CLI/GUI entrypoint |
| `gui_app.py` | Tkinter GUI, SSH/SCP workflow, Open/Export/Compare actions |
| `log_core.py` | Parsing, transaction correlation, log export, local source handling, mappings, and response-code logic |
| `requirements.txt` | Python dependency pins |
| `README.md` | Project behavior and operational documentation |
| `AGENTS.md` | Repository-specific development instructions |

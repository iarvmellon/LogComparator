# LogComparator

LogComparator is a Windows desktop utility for downloading TANGO logs and
building complete, readable transaction flows from PTMS/SPDH and OPN/ISO audit
streams.

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

1. Connect to the configured TANGO server with Windows OpenSSH.
2. List remote `tango.log*` files.
3. Show their dates in a calendar; valid dates are highlighted.
4. Require a bank/acquirer selection.
5. Optionally accept an exact `TransUID`.
6. Locate the daily Tango log, PTMS audit, and selected bank OPN audit.
7. Download missing files into the bank's `source` directory.
8. Parse all selected audit files as one chronological dataset.
9. Group records into complete transaction flows.
10. Generate a full log and a summary log for every selected transaction.

Progress, errors, and completion statistics are printed in the console. No
completion dialog is opened after the calendar closes.

## GUI controls

### Calendar

Only highlighted dates can be selected. The selected date determines the
`tango.log` and audit filenames searched on the server.

### Bank/Acquirer

The bank controls the OPN audit process and the bank-filtering rules.

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

### TransUID

The TransUID field is optional:

- Empty: generate every transaction that matches the selected bank.
- Filled: generate only the exact matching `transUId`.

A targeted run does not create `NO_TRANSUID.log` and does not delete or
rewrite unrelated existing transaction files.

## Downloads and cache

Downloaded files are stored under:

```text
LogComparator\<BANK>\<YYYY-MM-DD>\source
```

The bank name is made Windows-safe, so `CASYS/FIBANK` becomes
`CASYS_FIBANK`.

If a remote basename already exists locally, SCP is skipped:

```text
Using existing file: ...
```

If a downloaded `.gz` file already has a decompressed sibling, decompression
is also skipped:

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
        20260619_082537_<transUId>_<RRN>_Purchase_Approved(00)_Approved(000).log
        20260619_082537_<transUId>_<RRN>_Purchase_Approved(00)_Approved(000)_summary.log
        NO_TRANSUID.log
        source\
            tango.log.2026-06-19
            audit.PTMSPMLN01.2026-06-19
            audit.OPNBISOCAS01.2026-06-19
```

Every normal transaction produces two files:

1. `<transaction>.log`
2. `<transaction>_summary.log`

When a transaction is regenerated with a changed filename, old filename
variants for the same `transUId` are removed.

## Filename format

```text
YYYYMMdd_HHmmss_<transUId>_<RRN>_<TRANSACTION_NAME>_<ISO_DESCRIPTION>(<ISO_RC>)_<SPDH_DESCRIPTION>(<SPDH_RC>).log
```

Rules:

- The timestamp is the earliest request timestamp.
- Missing date/time becomes `UNKNOWN_DATETIME`.
- Missing RRN becomes `NO_RRN` in the filename.
- Missing response code becomes `Not_available(NA)`.
- An unmapped response code becomes `Unknown_response_code(<value>)`.
- Windows-unsafe characters are normalized.
- The ISO RC appears before the SPDH RC.

Example:

```text
20260619_082537_36178713733611102100139_000537001063_Purchase_No_card_record(56)_Invalid_expiration_date(206).log
```

## Full transaction log

Both `.log` and `_summary.log` files begin with a structured transaction
summary:

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

The full log is the detailed diagnostic artifact.

## Summary log

The `_summary.log` uses the same transaction summary and flow, followed by:

1. Exact matching `tango.log` lines.
2. Only external PTMS/OPN network audit blocks.

Only these detailed audit directions are included:

- `NETWORK-->TANGO`
- `TANGO-->NETWORK`

Internal REQUEST/RESPONSE audit blocks are not copied below the diagram.
`Bus data:` is removed from summary blocks, while `Audit data:` remains.

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
choosing the filename transaction description.

Dots shown in database displays are removed in audit values:
`4.530` is parsed as `4530`.

| Transaction MTI | Reversal MTI | Filename description |
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

Reversal filenames use the original description plus `_Reversal`, for
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

Without positional audit files, `main.py` opens the GUI.

## Installation

Requirements:

- Windows with Python 3.
- Windows OpenSSH `ssh` and `scp` on `PATH`.
- Network access to the configured server.
- Permission to run the required remote commands through `sudo`.
- Python packages from `requirements.txt`.

Setup:

```powershell
cd C:\Users\j.arvanitis\Desktop\Tango\github\LogComparator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Configuration

The following values are configured near the top of `main.py`:

- SSH host, port, user, and timeout.
- Remote Tango log and audit directories.
- Local output root.
- Bank-to-OPN mappings.
- Bank acquirer identifiers.
- TANGO/ISO MTI descriptions.
- ISO/SPDH response-code descriptions.
- Correlation window.

Security note: the sudo password is currently stored as plain text in
`main.py`. Keep the repository and its copies appropriately protected.

## Notepad++ EnhanceAnyLexer

Colored log highlighting requires the **EnhanceAnyLexer** Notepad++ plugin.
The generated log files remain plain text and can be opened without the plugin,
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
2. Open a generated `.log` or `_summary.log` file.
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

Run the analysis again for the same transaction. Generated variants for that
`transUId` are cleaned when the transaction is regenerated. Targeted runs do
not remove unrelated transactions.

### Ctrl+C

The calendar periodically returns control to Python so Ctrl+C can be processed.
SSH/SCP subprocesses are also bounded by configured timeouts.

### No new download occurs

The source cache is active. Remove the corresponding file from the bank and
date-specific `source` directory when a fresh download is required.

## Project files

| File | Purpose |
| --- | --- |
| `main.py` | GUI, SSH/SCP, parsing, correlation, naming, and output generation |
| `requirements.txt` | Python dependency pins |
| `README.md` | Project behavior and operational documentation |
| `AGENTS.md` | Repository-specific development instructions |

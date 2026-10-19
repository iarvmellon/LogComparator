# LogComparator

LogComparator loads TANGO logs and builds complete transaction flows from
PTMS/SPDH and OPN/ISO audit streams. **The NiceGUI / Quasar web interface is now
the only UI.** The former Tkinter window and its calendar/layout code have been
removed. Parsing, transaction checks, CLI analysis and export formats are retained.

The top toolbar keeps **Compare** on the first row with **Open** and **Export**. Selected date and each action button have 40px spacing between them for easier reading.
**Time range** keeps From, To and Timezone on one row, and **Filters** keeps
all fields, including Possible problem, on one row. The toolbar and Filters
can scroll horizontally when the window is too narrow.
The **Data** and **Time range** panels share one row. All **Data** controls use
a compact single row. All fields in **Data** and **Time range** use the original
40px Bank/Acquirer height. Data and Time range have no scrollbars: fields resize
to fit, the panels stack on narrow windows, and Data controls use two rows on
small screens.
Hover over its shortened live status to read the full message. The workspace
fills the browser viewport; the table uses the remaining height and provides
the only vertical scrollbar, with its header and pagination kept visible.
Column headers are 2px larger than row text and use a heavier bold weight.
Column widths start from the widest filtered value or header, then shrink
together to fit the available table width so the last column is fully visible.
The selection checkbox column keeps a fixed 44px width. Truncated values show
the full value on hover. Widths
update after loading, filtering, changing visible columns or changing font size.
Possible problem displays at most 100 characters, including the trailing `...`.
Hover over it to read the full description; filters and exports retain the full text.
Progress is shown only in the last footer row. Its space stays reserved while
idle, so progress and status changes never resize the transaction list.

For today's remote sources, `.tar.gz`/`.tgz` archives and `.gz`/`.gzip` files
are streamed over SSH/SFTP and decompressed in RAM without local source files.
For all earlier dates, compressed and uncompressed sources are downloaded to the
local import cache; archives are retained and extracted locally. Historical
sources have no live updates. Open, Compare and export use the resulting snapshots.
Uncompressed sources for today retain their incremental local mirror.

Connection messages identify the affected link: **Browser <-> LogComparator** in
the reconnect overlay, or **SSH (LogComparator <-> remote host:port)** in the live
status. The browser reconnect overlay does not indicate an SSH disconnection.

Ready transaction lists and diagnostics are cached per Bank/Acquirer, date and
source folder, with a total budget of 250,000 cached rows (one large result may
exceed this budget). Returning to an unchanged bank reuses the
ready results. Changes to its audit files or shared Tango/PTMS sources invalidate
the cached results. Remote imports also prepare other banks in the background
after reading their files. Ready banks can open while another bank is being
prepared; foreground loads take priority at background analysis checkpoints.
Banks that have not finished preparation still require analysis.

The Bank/Acquirer selector stays available while progress is shown. If an
operation is in progress, the latest selected bank opens when that operation
finishes. Changing Bank/Acquirer immediately clears the transaction table and its
selection; it stays empty with an animated loading bar until results for the
selected bank are ready. The loading bar does not show an estimated percentage.

Transaction preview tabs are standalone snapshot pages. They open immediately
with a loading indicator and fetch the log once over HTTP, independently of the
main workspace live updates and WebSocket reconnects. There is no automatic
preview refresh or polling; the displayed log stays fixed until you reload or
reopen it. Slow exports can exceed three seconds without a page timeout.
The indicator is replaced by the log and Download link, or an error message.

A LOGON with an ISO 0800 TANGO-to-NETWORK request and an ISO 0810
NETWORK-to-TANGO response from the same process is green, including audits that
omit the response code. Three-digit 800/810 MTIs are normalized to 0800/0810.
A standalone inbound LOGON 0800 NETWORK-to-TANGO is also green without requiring
an 0810 response. A standalone outbound 0800 still requires its 0810 reply.
An explicit non-approved response code does not qualify; existing diagnostic
errors and warnings retain their row-color priority.

Selected transactions have a blue outline around the row instead of a blue
fill. Their green, yellow or red diagnostic background and normal text/link
colors remain visible. The outline does not change row height or column widths.

OPN network-management messages with DE70 `201` are displayed as
**Cutoff Initiation / Cutover**, with the observed request/response flow suffix,
instead of Network_Management.

## Start the application

Open `dist/LogComparator.exe` using the existing Desktop shortcut. It starts the
web server and opens the browser. The executable remains at the fixed project
path `dist/LogComparator.exe`; no Python, Node, Tkinter, WinMerge or Notepad++
installation is needed to use the packaged application. The local diff2html
JavaScript, CSS and license are included in the executable. The Windows build
uses `--noconsole`: it runs the web server in the background without opening a
terminal window. Diagnostics are written to
`%LOCALAPPDATA%\LogComparator\LogComparator.log`.

From source, run from the project root using the project virtual environment:

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe main.py
# Alternatives:
.\start_web.ps1
.\.venv\Scripts\python.exe main.py --no-browser --port 8080
```

The server listens on `0.0.0.0:8080`. Locally, use `http://127.0.0.1:8080`;
other computers can use `http://<server-IP>:8080` if network routing and the
existing firewall allow the connection. Starting the executable again opens the
already-running LogComparator server instead of starting a conflicting copy.
Use `--port 8081` for another port. Keep the server process running. To stop
the background Windows executable, end LogComparator in Task Manager. For
source/terminal runs, Ctrl+C stops the server; use `python main.py` for CLI
output in a terminal. **File > Close workspace** closes only that browser
workspace so other users can continue working.

The interface has no login. Users who can reach it can access the server's log
folders and configured UAT operations; run it on a trusted internal network.
Settings, source selection, filters and export options are separate per browser
workspace. SSH settings are applied in the worker context instead of changing
another user's credentials. Refreshing the page starts a fresh workspace.

## Workflow and controls

- **File > Import local logs** opens a server-folder import dialog. Type a path or use
  **Browse folders**, set the separate Audit folder if needed, choose the log
  date and bank/acquirer and press **Load folder**. Available choices load
  automatically when Import opens or source paths change. One date can be selected automatically; multiple
  dates require a selection. Compressed files are extracted into a writable
  cache without modifying the source directories. The Log/Audit fields show the chosen sources. A folder
  path refers to the server computer, including when accessed from another PC.
  With a configured audit directory (Docker/Linux), the dialog uses the
  configured log/audit directories automatically and shows date/bank choices
  without path fields or folder browse buttons.
- **File > Import remote logs (UAT)** imports Tango logs and audit files from a
  remote Linux server using SSH/SFTP. Host, port, username, password and source
  folders use the existing hardcoded UAT configuration; none of these fields
  are displayed or editable in the browser. Opening the dialog automatically
  connects and lists the available logs; no separate connection button is needed.
  Temporary SSH timeouts/disconnections retry automatically up to three attempts
  (one- and two-second delays). Connection timeout is 30 seconds; SSH banner,
  authentication, channel opening and directory reads allow 60 seconds. Keepalive
  packets are sent every 15 seconds. After the attempts fail, **Retry listing**
  retries in the same dialog. Closing the dialog prevents further retries.
  Authentication, permissions and host-key failures are not retried automatically.
  The remote folders are `/opt/tango/MLNPSP01/log` and
  `/opt/tango/MLNPSP01/audit`, matching the local Linux source layout.
  The historical stored sudo password is used as the SSH password fallback;
  existing SSH agent/default keys are also tried. SHA256 host fingerprints are
  accepted automatically whenever a new remote connection workflow requires
  acceptance, including when reopening the dialog. Acceptance happens inside the
  first SSH handshake, without disconnecting and opening a second connection.
  No confirmation button is shown. Subsequent reads in that workflow
  reuse the accepted fingerprint; a changed key within the workflow is rejected. Choose an available
  date directly in the calendar (green dots identify available dates), and **Remote Bank/Acquirer**, then **Read remote logs**. Only the selected bank is loaded and displayed first;
  there is no foreground All option.
  The requested bank's OPN and shared PTMS audits load first; other banks download
  in the background and become available through the bank combobox.
  If a date contains PTMS/SPDH audits only, the bank selector offers the configured
  banks and the parser applies transaction-level bank filtering after download.
  Files are read over SSH/SFTP into a private folder under the writable source
  cache for uncompressed sources, with atomic publication of bounded file snapshots.
  Today's compressed sources are streamed and extracted in RAM; historical sources
  are downloaded and extracted locally. Date discovery uses log and
  audit filenames; the selected date's Tango logs are read too, so the
  same Tango diagnostics can run as with a local import.
  The password stays in the server-side UAT configuration; there is no password
  input, prefilled password value or credential override in the web dialog.
  Remote import first logs in over SSH as `j.arvanitis`, then uses `sudo` to
  start an elevated SFTP server for listing and reading the log/audit folders.
  The sudo password is sent only when sudo prompts, never in the command line.
  Passwordless sudo also works without sending a password into the SFTP stream.
  The remote account needs sudo permission to run the existing SFTP server binary.
  A stalled TCP opening is retried once with a fresh connection after a 10-second
  timeout, before authentication. Authentication and sudo failures are not retried
  by this step. Persistent TCP timeouts identify the stage before SSH login and sudo. The remote host needs its
  SSH service and SFTP subsystem available. LogComparator uses Python Paramiko,
  so no SSH/SCP executable or Linux system package needs to
  be installed in the LogComparator container. Connections originate from the
  server/container, not the browser PC. The remote files remain unchanged.
  **Live update** is always off when the GUI starts and after a new local or
  remote import. Enable it manually for today when needed.
  Historical imports remain readable but their Live update checkbox is disabled. A persistent SSH/SFTP
  connection checks today's log/audit files approximately every
  500 ms (plus network, file-reading and parsing time). Only appended bytes are
  read after the initial snapshot, with small prefix checks to detect rotation
  or truncation. Only the selected Bank/Acquirer is monitored live, including its new audit files
  and shared PTMS/Tango sources. Changing Bank/Acquirer switches monitoring; other
  banks receive one background snapshot and are not continuously refreshed. Replaced
  or truncated files are read again; rotated files remain in the local history.
  Interrupted reads retain the last complete cache. Lost connections reconnect
  automatically using the automatically accepted host fingerprint; a changed key is rejected.
  Disable **Live update** to pause remote reads, or enable it to resume.
  Today means the date on the computer/container running LogComparator,
  independent of the display timezone. At midnight the old live session stops;
  import the new date explicitly. Other banks for the imported date, including today, are read
  once in the background, without continuous remote polling.
- The requested bank is displayed first. A separate background worker
  loads other banks for the same date once, independently of the Live update checkbox.
  Bank/Acquirer switches reuse these files. A bank selected before its files
  arrive loads when they become available. Importing another source, closing the
  workspace or deleting its browser session stops the old SSH reader.
- **From / To** each combine date and time. Click the field or calendar icon to
  choose a date and a 24-hour clock time, including seconds, then Apply. Cancel
  retains the old range. Bounds include the entire final second. Timezone is
  restricted to UTC-3 through UTC+3. Changing it shifts displayed timestamps and
  range bounds together to retain the selected instants.
- Enable **Live update** in Data after a local filesystem import to follow growing
  local logs for today. Events for older dates are ignored.
  Filesystem notifications trigger updates for the current date and
  bank, reloading only after changes, additions or rotation. Events are grouped
  for about 50–250 ms and checked by the UI every 250 ms; parsing time adds to
  this delay. A five-second metadata check also catches missed events on network
  shares and retries incomplete reads. Updates run
  in a worker and preserve filters, From/To, timezone, sorting, pagination and
  selected transaction IDs that remain visible. Updated responses/diagnostics
  replace the corresponding rows. Live update stops at midnight;
  import the new current date explicitly. Disable the checkbox to pause updates.
  Failed reads (including incomplete gzip files) retain the last successful list
  and retry on the next check; the live status shows the error. This polls local
  files only and does not repeat SSH downloads. Large files may take longer than
  a few seconds to parse; scans never overlap within a workspace. Disabling live
  updates, closing the workspace or deleting the browser session stops its watcher.
  Remote imports use the SSH/SFTP live reader described above.
- **Filters** combine case-insensitive substring searches. **Possible problem**
  is always shown last at a wider size; it searches the displayed combined
  ISO/SPDH text, without hidden severity prefixes. Other filters are TransUID,
  STAN, RRN, AuthCode, Sequence_Number, TransactionType, TID, MID, AMT, RC_SPDH
  and RC_ISO. **Edit > Clear filters** resets text filters.
- Click a row or its checkbox to select it. **Edit** includes Select all visible
  and Clear selection. Headers sort columns; the table supports horizontal
  scrolling and pagination. **View > Columns / Filters** controls both column
  and corresponding filter visibility, clearing a hidden filter. Possible
  problem remains visible. **View** adjusts table font size; browser Ctrl +/-
  zooms the whole interface. Controls wrap on narrower screens.
- **Open**, a TransUID link, or double-clicking a row opens that transaction's
  exported log in a separate browser tab, with Download log. Each link resolves
  to that specific UID and current export options. Very old links expire after
  32 source loads across workspaces; reopen the transaction from the main table.
  For one selected row, the toolbar Open action is a direct browser link.
  Opening several rows also presents individual links for each selected log.
- **Export** downloads selected rows, or all visible rows when none are selected.
  One transaction downloads as a log, multiple transactions as a ZIP. Copies are
  also saved under the configured output folder in `<BANK>/<YYYY-MM-DD>`.
- **Compare** requires exactly two selected rows. It uses **diff2html**, with
  read-only side-by-side logs, colored insertions/deletions, line matching,
  synchronized horizontal scrolling, previous/next difference controls and a
  downloadable unified diff. It reports identical exports explicitly. It does
  not run WinMerge or Monaco and does not change either original log. All
  renderer resources are served by LogComparator, with no CDN dependency.
- Right-click a row for **Open / Export / Compare**. If that row was not selected,
  it becomes the current selection; an existing multi-selection is retained.
  Open/Export are also under File and Tools. Compare is under Tools.
- **Tools > Export options** and the toolbar share protocol selection
  (SPDH+ISO / ISO / SPDH), Include Byte/Data, Tango Internal, Tango to Network
  and Network to Tango. New previews and comparisons use the current options.
- **File > Settings** changes the current workspace's output folder. Browse
  output folder uses the web folder chooser. Remote credentials are entered
  separately in **Import remote logs (UAT)**; there are no SSH/sudo fields in Settings. **Help > About** shows the release, Git commit and author.

## Linux server with Docker

Docker/Linux offers exactly two import choices: **Import local logs** reads
the filesystem directly; **Import remote logs (UAT)** reads the same directory
layout on the selected remote host through SSH/SFTP. The local mode uses these
read-only source mounts in `compose.yaml`:

- `/opt/tango/MLNPSP01/log` for Tango logs.
- `/opt/tango/MLNPSP01/audit` for bank audit files.

From the project directory on the Linux server, with Docker and Compose available:

```sh
cp .env.docker.example .env
# Set TANGO_READ_GID in .env to an existing group that can read both directories.
docker compose up -d --build
docker compose logs -f logcomparator
```

Open `http://<server-IP>:4020`. Use **File > Import local logs** to select an available
date and bank. Configured server source folders are used automatically; the
Import dialog omits folder path fields and folder browsing controls when an
audit directory is configured (as in Docker/Linux). Available dates and banks
load automatically each time Import opens; there is no inspection button. All local banks remain
available through Bank/Acquirer. The File menu has only the two import choices
above; the former SSH/SCP (UAT) and duplicate generic remote import entries have
been consolidated. Both choices are available in Docker/Linux.

Docker publishes host TCP 4020 to container TCP 8080. The application and
container continue listening on 8080; only the external port changes. Set
`LOGCOMPARATOR_PORT=4020` in existing `.env` files and allow TCP 4020 through
the server firewall. For an existing image listening on 8080, this change needs
no image build: update the Compose port mapping to
`"${LOGCOMPARATOR_PORT:-4020}:8080"`, then run:

```sh
docker compose up -d --no-build --pull never
```

Compose recreates the container with the updated published port and preserves
its mounted data volumes.

The container runs as UID/GID `10001:10001`, with the supplementary group
`TANGO_READ_GID`. This user/group needs read access to the files and traversal
access to their parent directories. The bind sources must already exist.
Change `TANGO_LOG_DIR`, `TANGO_AUDIT_DIR` or `LOGCOMPARATOR_PORT` in `.env`
if the server uses different locations or a different external port.

Named volumes preserve exports (`/data/exports`), extracted gzip cache
(`/data/cache`) and application state (`/data/state`) across container recreation.
Source files are never extracted in place. `docker compose down` preserves
these volumes; `down -v` deletes them. The image includes a `/health` check.
No Linux system packages or SSH client are installed by the Dockerfile.

If building reports a timeout reaching `auth.docker.io`, the Docker daemon
cannot reach Docker Hub over HTTPS. The Dockerfile uses the bundled frontend
and does not download `docker/dockerfile:1`. For an older copy, remove its first
`# syntax=docker/dockerfile:1` line and retry. Pulling the Python base image still
requires Docker Hub access, and installing Python dependencies requires PyPI
access. Check server routing/firewall and Docker daemon proxy settings if
`docker pull python:3.13-slim-bookworm` also times out; changing the container's
group ID does not affect registry connectivity.

For source runs, `LOGCOMPARATOR_LOG_DIR`, `LOGCOMPARATOR_AUDIT_DIR`,
`LOGCOMPARATOR_OUTPUT` and `LOGCOMPARATOR_CACHE` configure the local paths.
Linux defaults use the two `/opt/tango` directories above. Remote UAT import is
available independently of the legacy `LOGCOMPARATOR_ENABLE_SSH` setting.

### Update through Git and transfer the Docker image

If the machine running Docker does not contain `/opt/tango/MLNPSP01/log` and
`/opt/tango/MLNPSP01/audit`, the standard Compose file reports
`bind source path does not exist`. Its mounts refer to the Docker host, not to
a remote SSH server. Use the standalone remote-import deployment instead:

```bash
docker compose -f compose.remote.yaml up -d --no-build --pull never
```

This requires the updated application image containing **Import remote logs (UAT)**.
To build on a machine with dependency-download access, use
`docker compose -f compose.remote.yaml up -d --build` instead. The remote Compose
file mounts only exports/cache/state volumes and needs no local Tango directories.
It publishes the same external 4020/internal 8080 ports. Enter the actual remote
the configured UAT connection through **File > Import remote logs (UAT)**. The remote host uses
the fixed `/opt/tango/MLNPSP01/log` and `/opt/tango/MLNPSP01/audit` folders. Use
`docker compose -f compose.remote.yaml ...` for subsequent status/log/update
commands in this deployment mode; do not start both Compose modes together.

Use this procedure when Windows can build the image but the Linux server cannot
download Docker/Python dependencies. Run all commands from the project directory.
Docker Desktop on Windows must use Linux containers. The commands below target
an Intel/AMD 64-bit Linux server (`linux/amd64`); use `linux/arm64` for ARM64.

1. On Windows, commit and push the code changes to Git. Then build the image
   from that same version and export it:

   ```powershell
   docker build --platform linux/amd64 --build-arg BUILD_DESCRIBE="$(git describe --tags --always --dirty)" --build-arg BUILD_GIT_HASH="$(git rev-parse --short=12 HEAD)" -t logcomparator:local .
   docker run --rm --entrypoint python logcomparator:local -c "import log_config; print(log_config.APP_BUILD_DESCRIBE)"
   docker save -o logcomparator.tar logcomparator:local
   ```

   Keep both `--build-arg` options: they embed the Git version and commit in the
   image for the browser tab and **Help > About > Version**. A plain
   `docker build -t logcomparator:local .` uses the default `container` label;
   copying the image to a Git checkout on Linux does not add version metadata.
   Run the build in the Windows Git checkout, with Git available on PATH.
   Before transferring the archive, verify that the printed version is the
   expected Git version, not `container`.

2. Transfer the new `logcomparator.tar` to the project directory on the Linux
   server using your usual file-transfer method. The archive contains the
   complete application image, not just the Python base image. Transfer it
   separately; do not commit it to Git. Keep the server's `.env` and credentials
   outside Git as well.

3. On Linux, load the archive and
   recreate the container without building or pulling an image:

   ```bash
   docker load -i logcomparator.tar
   docker compose up -d --no-build --pull never --force-recreate
   ```

   Preserve the server's existing `.env`, including `LOGCOMPARATOR_PORT=4020`
   and its source paths/group ID. Application-only updates do not require
   `git pull`: the new application code is already inside the image.
   If deployment files such as `compose.yaml` have also changed, update those
   files with `git pull` (or transfer them separately) before recreating the
   container. The Compose configuration must be compatible with the new image.

4. Wait for the application to be ready before checking its version. A started
   container does not necessarily mean the web server is ready: an immediate
   `curl` can report `Connection reset by peer` during startup. The following
   Bash commands try the health check up to 30 times, with a two-second pause
   between attempts and a three-second timeout per request:

   ```bash
   ready=false
   for attempt in {1..30}; do
     if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:4020/health; then
       printf '\n'
       ready=true
       break
     fi
     sleep 2
   done
   if [ "$ready" = true ]; then
     docker compose ps
   else
     echo "Application is not ready; inspect container status, logs and port mapping:"
     docker compose ps
     docker compose logs --tail=100 logcomparator
     docker compose port logcomparator 8080
   fi
   ```

   After the health check succeeds, open `http://<server-IP>:4020` and use
   Ctrl+F5. The published port is 4020 and the internal application port is 8080.
   Recreating the container preserves its mounted
   log sources and named data volumes; do not use `docker compose down -v`.
   The health response's `version`, browser tab and About's Version field should
   show the Git build version, for example `v1.0.29-6-g1974451`. If they show
   `container`, rebuild on Windows with the metadata arguments above, export and
   transfer the new archive, load it and recreate the container. Then use Ctrl+F5.

A code change needs a new image build and archive. Changing only the published
host port in Compose/`.env` does not require a new image or archive.

If an optional `git pull` is blocked because an untracked `logcomparator.tar`
would be overwritten, first preserve the local archive outside the checkout:

```bash
mv logcomparator.tar "../logcomparator-backup-$(date +%Y%m%d-%H%M%S).tar"
git pull
```

This resolves the file conflict only; it does not update the running container.
Load the intended new archive and recreate the container using step 3. If an
older commit tracked `logcomparator.tar`, remove it from Git tracking in a future
commit (`git rm --cached -- logcomparator.tar`) and add `/logcomparator.tar` to
`.gitignore`; continue transferring archives separately.

The browser tab title shows `LogComparator <build version>` on the main page
and transaction tabs. The Windows Docker build command above embeds the Git
version and commit so the title identifies the installed image. For Compose
builds, set `LOGCOMPARATOR_VERSION` and `LOGCOMPARATOR_GIT_HASH` in the local
`.env` to the desired Git describe/commit values before building. Without build
metadata, Docker images use the default `container` label in the title and
About's Version field. These values are embedded at build time: changing `.env`
and restarting an existing image does not change its version metadata.

## Migration from the native UI

| Former UI function | Web equivalent |
| --- | --- |
| Native window and date dialogs | Browser page and Quasar calendar/time pickers |
| Native folder chooser | File > Import local logs > Browse folders |
| SSH date and selected-bank import | File > Import remote logs (UAT) |
| Background download for other banks | Background worker and bank combobox |
| Table filters, columns, sorting, selection, colors | Quasar QTable and filter bar |
| Open in Notepad++ / double-click | Specific transaction in a new browser tab |
| Compare in WinMerge | Bundled diff2html side-by-side comparison |
| Export logs to disk | Saved server exports plus log/ZIP browser download |
| Right-click Open / Export / Compare | Row context menu |
| Export options, settings, font size and About | File / Tools / View / Help menus |
| Exit native window | File > Close workspace; Ctrl+C stops the shared server |

## Installation and building

For source/development use, install Python 3.10+ and Git for Windows. Run
`setup.ps1` to create/reuse `.venv`, install application/build dependencies and
register the project's PyInstaller asset hook. `requirements-web.txt` remains a
compatibility alias for `requirements.txt`. The web remote import uses the
Python Paramiko/scp dependencies and requires network access to the remote SSH
port and read permission on both remote source directories. No local OpenSSH
executable or Linux system package installation is required.

Build from the project root with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe update_build_info.py
.\.venv\Scripts\pyinstaller.exe --onefile --noconsole --name LogComparator --add-data "build_info.json;." main.py
```

The locally installed `logcomparator-web-ui` package supplies a PyInstaller hook
that collects the custom component and diff2html assets. The standard NiceGUI
hook includes Quasar, Vue and other browser resources. The finished executable
must always be at `<project>/dist/LogComparator.exe`; the Desktop shortcut keeps
pointing to this fixed path. `build/`, `dist/` and the generated spec are ignored.
`build_executable.ps1` performs a local build. `create_release.py` publishes the
next annotated release tag and builds it after source changes have been committed.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pip install -r testing/requirements-web-test.txt
.\.venv\Scripts\python.exe -m pytest testing -q
.\.venv\Scripts\python.exe -m unittest discover -s testing -t . -q
node testing/test_diff2html.js
node testing/test_table_sizing.js
```

Python tests use synthetic source files and mocked SSH calls. They cover loading,
combined diagnostics, time and text filtering, settings isolation, background
publication, specific-transaction previews, comparison, export and bank switching.
Remote tests use a loopback SSH/SFTP/SCP server to verify password authentication,
fingerprint checks, discovery, SSH/SFTP live appends, truncation, new files,
reconnection, legacy SCP downloads, atomic failure handling and
background transfers without accessing a production host.
The NiceGUI simulated-user test runs under pytest and is skipped by unittest.
The Node development test checks the actual vendored diff2html renderer, escaping
of log text and synchronized scrolling; Node is not needed by the server or EXE.

## Configuration and source cache

Constants and protocol/bank mappings are in `log_config.py`; parsing and export
are in `log_core.py`. Remote UAT host/user/password use the existing server-side configuration;
Settings controls only the output folder.
The Windows default output folder is `C:\Users\j.arvanitis\Desktop\Tango\LogComparator\Logs`;
the Docker/Linux default is `/data/exports`.
Remote UAT imports are stored in private `remote-*` source-cache folders. Each
new remote import starts a fresh SSH/SFTP cache; bank switches reuse its live cache. Local imports are parsed from their selected folder. Parsed-list
caching is bounded and keyed by source path, modification time and size; source
changes invalidate it. Blocking work runs outside the web event loop and shared
parser caches are serialized. Download/preview variants use private temporary
folders, then copies are atomically published in the configured output directory.
Temporary variants are cleaned when the server exits; published exports remain.

## Diagnostic behavior

Large audit files are scanned with memory mapping. The transaction-list loader
decodes only blocks containing a transaction ID and retains transaction metadata
instead of caching full multi-gigabyte file contents, substantially reducing RAM
usage and initial loading time.

The transaction list has one shared `Possible problem` column for ISO and SPDH.
Duplicate findings appear once. Severity prefixes (`warning:` / `error:`) are
hidden in the displayed text; row colors identify severity: yellow for warnings,
red for errors, with red taking priority when both occur. When request and
response RRN values differ within the same OPN process, `Possible problem` displays
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
When both problems apply, both messages appear in the shared Possible problem column.

Diagnostic rules are separate from the web interface and core log parser:

- `iso_checks.py`: ISO field extraction and checks.
- `spdh_checks.py`: SPDH field extraction and checks.
- `tango_checks.py`: streaming Tango diagnostic detection and exact transaction matching.
- `transaction_checks.py`: RRN checks and orchestration of the ISO/SPDH diagnostics.
- `diagnostic_common.py`: shared metadata, comparisons, original lookup, and row severity.
- `emv_checks.py`: shared basic EMV extraction, format checks, and completeness warnings.

Basic EMV checks apply separately to ISO and SPDH messages. Explicit decoded tag
names (for example `tag9F26`) and XML fields are supported. Named EMV components
are recognized in ICC/EMV audit data. Explicit `hex<...>` ICC/EMV containers,
including ISO `DE55`, are parsed as BER-TLV with constructed templates and
long-form lengths. Proprietary SPDH fixed-layout request fields are not treated
as TLV. Integer audit renderings and opaque binary dumps are not assigned byte
lengths because their original encoding is unavailable.
Named ASCII country/currency audit fields such as `terminalCountryCode : asc<008>`
are decoded three-digit numbers, not raw hexadecimal bytes. Their omitted BCD
padding nibble is restored for EMV validation; raw hex tags and TLV retain
strict byte-length checks.
XML `type='A'` fields use the same decoded ASCII rules, including numeric country
values with omitted leading zeros. Named binary ASCII fields are accepted only
at their known fixed widths. Padded transport fields, variable-length named IAD,
and XML `TH` dumps are not interpreted as raw EMV tags. Ambiguous named audit
representations are excluded from comparisons; conflicting explicit wire tags
still produce red findings.

Red findings identify malformed hexadecimal values, incorrect known tag lengths,
invalid packed-decimal values or dates, conflicting values for the same tag,
and malformed/truncated TLV. Fixed lengths cover cryptogram, ATC, unpredictable
number, TVR, AIP, date, transaction type, amount, currency/country, and basic
terminal/CVM tags. IAD remains opaque and is checked only for its 1–32 byte range.
These data-object lengths follow the
[EMV tag reference](https://developer.cybersource.com/docs/cybs/en-us/cp-retail/integration/eftpos/rest/cp-retail/cp-pymnt-svcs-eftpos-intro/cp-retail-eftpos-emv-tags.html);
that provider's mandatory-tag profile is not imposed on other acquirers.

Yellow warnings identify missing common online EMV tags when an ISO `0100`/`0200`
request contains decoded EMV data, or an SPDH request explicitly contains ARQC
CID `80`. Chip entry modes `05`/`07` without decoded EMV data are also warnings.
Missing tags are not treated as universally mandatory: acquirer requirements
and audit completeness must be verified. Responses, ISO reversals/advice and
network requests do not inherit the online authorization tag checklist.
Differences between EMV amount/currency and message values are warnings,
because mappings and surcharge/partial-approval behavior can legitimately differ.

Additional basic format checks validate explicitly numbered ISO DE7 date/time
and decoded SPDH nonnegative amount, numeric currency (up to 3 digits), and
numeric STAN (up to 6 digits). Missing optional fields remain unflagged.
For CASYS, NEXI/ALPHA, BORICA/PROCREDIT and EUROBANK, an explicitly identified
ISO Echo request is a one-way heartbeat: no response is expected. ISO network
requests with DE70 `301` (or dedicated Echo MTIs `0860`/`7080`) do not trigger
the missing-response warning for these process families. Transactions containing
only these ISO requests and no SPDH messages are green when no other diagnostic
applies. Errors and warnings still override green; Logon, payment requests and
Echo requests for other acquirers retain their normal checks. Response codes
remain `Unknown` when no response exists; no approval code is fabricated.
All findings use the shared `Possible problem` column and row colors: red for errors,
yellow for warnings, with red taking priority. No bank-specific mandatory fields
or cryptographic verification is assumed.

Additional ISO checks run on decoded OPN request/response records in both parsers.
They compare messages within the same transaction and OPN process, using known
ISO MTI pairs and STAN to distinguish multiple exchanges. Internal and SPDH
records do not participate in these ISO checks. Original STAN fields are kept
separate from the current STAN. Numeric padding is ignored for STAN, amount,
and currency comparisons; absent fields are not treated as different values.

| Finding in `Possible problem` | Highlight |
| --- | --- |
| `different STAN on the same transaction` | Red |
| `currency mismatch` | Red |
| `terminal or merchant mismatch` | Red |
| `unexpected response MTI` for a supported ISO pair | Red |
| `conflicting responses` with different response codes for the same MTI/STAN/process | Red |
| `original transaction mismatch` for a uniquely identified reversal/void original | Red |
| `invalid ISO message format (...)` for invalid explicitly numbered fixed-length fields or bitmap syntax | Red |
| `amount mismatch (check partial approval/adjustment)` | Yellow |
| `missing response code` for a supported response MTI | Yellow |
| Missing ISO request/response or original transaction | Yellow |
| Missing original reference or ambiguous pairing | Yellow |

Findings are combined in the shared `Possible problem` column. Red takes precedence over yellow,
and both take precedence over approved green. Declines alone are not flagged.
Original-transaction lookup uses DE90/original STAN when available, otherwise
original/current RRN, within the same OPN process across the loaded dataset.
Explicit decoded original STAN references take priority over raw DE90 slices.
BASE24 `retrievRefNumberOrigin`/`originMTI` fields are recognized as original
references; when present, DE90 is not guessed to contain ISO original STAN/DE7.
If a unique original is found, no missing-original warning is shown. Missing
or ambiguous originals still produce warnings, and actual reference mismatches
remain checked. The search covers all loaded transactions before table filters.
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
Explicit fixed-length numeric ISO `hex<...>` values are decoded as packed decimal only
when they contain decimal digits with the exact expected byte width (and a zero
padding nibble for odd-width fields). Other hexadecimal encodings are skipped.

These checks do not implement a bank-specific wire decoder: raw hexadecimal
payloads, binary encodings, bitmap-to-payload consistency, and LLVAR/LLLVAR
length prefixes cannot be certified from decoded audit fields. Format checks
cover explicitly numbered decoded fields (including `DE011` and XML forms)
with numeric widths DE3=6, DE4/5/6=12, DE7=10, DE11/12=6,
DE13/14/15/18=4, DE19/23/49/50/51/70=3, DE25/26=2 and DE90=42.
ASCII/unwrapped numeric values require the exact digit count; `int<...>` may
omit leading zeros but may not exceed that count. Absent, masked and opaque
values are skipped. Text fields DE37=12, DE38=6, DE41=8, DE42=15 and DE43=40
are checked for significant overlength; trimmed text and extra trailing audit
padding do not establish an error. DE52 is checked for exactly 8 bytes only
in explicit unmasked `hex<...>` form, and its value is never included in findings.
Logged hexadecimal/binary bitmap syntax is also checked.
Proprietary MTI pairings are not guessed. Amount changes and missing
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

The main window title displays the full build identifier.
Use **Help > About** to view the release tag, `git describe` build identifier,
exact Git hash, source state, and author (`IARV`). A value such as
`v1.0.21-3-gaadf381c63e5-dirty` identifies the nearest release, commit distance,
exact abbreviated commit, and uncommitted build changes. Versioning comes
entirely from annotated Git tags; there is no pre-commit version counter.
`build_info.json` is generated in the project root with `build_describe`,
`release_tag`, `git_hash`, and `git_dirty`. As in TangoWiresharkDisectors,
source runs read local Git on every launch, including after a fresh clone.
If Git is unavailable, they fall back to this JSON.
PyInstaller embeds `build_info.json` using `--add-data "build_info.json;."`;
the executable uses its embedded metadata. The executable needs
no external metadata file or Git installation. `build_info.json` is ignored by Git. Without Git or generated metadata,
source runs use an `untagged/development-unbuilt` fallback. 

For the same single-command build workflow as the dissector, run
`./build_executable.ps1`; it refreshes metadata without publishing a tag and
builds with the project virtual environment.

After every change, rebuild from the project root with:

```powershell
.\build_executable.ps1
```

The builder stages the new windowless executable in
`build/executable-stage/LogComparator.exe` while the existing app can continue
running. Only after PyInstaller succeeds, `publish_executable.ps1` stops processes
whose executable path exactly matches this project's `dist/LogComparator.exe`,
waits for them to exit and atomically publishes the new file. Other copies are
left running. File-lock errors are retried briefly. Failed builds leave the old
executable in place. Reopen the Desktop shortcut after a successful build.

If a release build failed with `WinError 5` after its tag was already published,
run the command above, or `.\.venv\Scripts\python.exe create_release.py --build-only`.
This retries the local build without creating or pushing a release tag. Administrator
rights are normally unnecessary; the release tag does not need to be removed.
Direct PyInstaller builds into `dist/` require closing the running application first.

The latest executable must always be stored inside the project at
`dist\LogComparator.exe`. Generated files under `dist/` are ignored and are
not tracked by Git, so rebuilding does not leave uncommitted executable changes.
`build/`, `dist/`, and all `*.exe` files are ignored by Git.
The Desktop shortcut points to this fixed path,
so each rebuild updates the version it opens. Reopen any running instance
to use the rebuilt version.

Release creation follows `TangoWiresharkDisectors`: ordinary commits and branch
pushes do not create tags. Commit the source changes, then run explicitly:

```powershell
.\.venv\Scripts\python.exe create_release.py
```

The script fetches tags from `origin`, creates the next annotated
`vMAJOR.MINOR.PATCH` tag on HEAD and pushes only that tag. The first release is
`v1.0.0`; subsequent releases increment the highest patch version up to `29`.
After `v1.0.29`, the next tag is `v1.1.1`; after `v1.1.29`, it is `v1.2.1`,
and so on. The minor version increases and the patch restarts at `1`, while
the major version remains unchanged. An already
released commit reuses its annotated tag and retries its push. Tag collisions
are retried without force-pushing or overwriting remote tags. Source changes
must be committed; generated files under `build/` and `dist/` may remain modified.
The script refreshes `build_info.json` after publishing and automatically rebuilds
`dist/LogComparator.exe` using the project virtual environment. This single
command creates the release and embeds its version in the executable. It does
not push the branch. If the build fails after publication, rerun the command:
it reuses the existing tag on that commit and retries the build.

To refresh only metadata without creating or pushing a release tag or building, run
`.\.venv\Scripts\python.exe create_release.py --update-build-info`
or the existing `update_build_info.py` command. The executable retains its
embedded version until rebuilt. No automatic tagging workflow is used.

Progress, errors, and completion statistics are printed in the console.

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

Network-management rows show `LOGON` or `ECHO` when ISO DE70 identifies the
operation (`001` or `301`), including named/XML `networkManageCode` audit fields
and MTIs `0800`/`0810`/`0820`/`0830`. Explicit Logon, Echo, Logoff/Sign-off,
and DCC Inquiry descriptions also provide specific labels. The observed
`ISOreq`/`ISOresp` suffix is preserved. Without clear operation evidence,
the row retains `Network_Management` rather than guessing from the MTI alone.
AKTIF/BKTKOS messages explicitly described as `MTI = 7140 - Loyalty Balance Inquiry`
are labeled `Loyalty Balance Inquiry`, even when transported as ISO `0800`/`0810`.
Processing code `890000` alone is not used to guess this operation.

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

Without positional audit files, `main.py` starts the web interface.


## Project files

| File | Purpose |
| --- | --- |
| `main.py` | Web-server launcher and retained audit-file CLI |
| `web_app.py` | NiceGUI / Quasar pages, menus, filters, source dialogs and browser actions |
| `web_services.py` | Parser adapters, bounded cache, worker settings, background jobs and exports |
| `gui_services.py` | Retained backend SSH/SCP and atomic audit publication helpers; no native UI |
| `logcomparator_ui/` | Local diff2html Vue component, vendored assets, license and build hook |
| `log_config.py` | Runtime defaults, bank/protocol mappings and response descriptions |
| `log_core.py` | Parsing, correlation, source handling and log generation |
| `pyproject.toml` | Local UI package and PyInstaller-hook registration |
| `requirements.txt` | Application dependency pins |
| `start_web.ps1` | Launch the primary web application from source |
| `testing/test_web_interface.py` | Backend and NiceGUI simulated-user integration tests |
| `testing/test_diff2html.js` | Vendored diff2html rendering/escaping/scroll test |

## Additional transaction semantics

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

EMV completeness warnings use transaction context: they apply to recognized
purchase/authorization requests. Void, reversal, refund, DCC, management,
security and unknown operations do not inherit the purchase EMV checklist.
Malformed explicit EMV tags and amount/currency comparisons remain checked.

SPDH-only reversals can also be green when each PTMS process has request/response,
all responses are `000`, and explicit original STAN or terminal/sequence references
uniquely locate an earlier original transaction in the loaded logs. The original
must have no observed ISO messages, OPN process or ISO flow, and original-reference
checks must pass. Missing or ambiguous originals, host-connected originals,
incomplete flows and declines do not qualify. Other warnings/errors retain
priority over green. This uses loaded-log evidence, not proof of host-side state.


### Audit-only Logon exchanges

Logon audit blocks with MTI 0800/0810 and DE70=001 are shown even when Tango
has not assigned a transUId. Request and response are grouped by process,
audit date and flow reference, using a visible LOGON-prefixed identifier.
These generated identifiers support row export and comparison; they are not
Tango transaction IDs. BKT/BKTKOS link Logons without acquirer IDs appear under
both banks because they use the shared OPNBISOBKT process. Explicit acquirer IDs
still restrict financial transactions and Logons to the matching bank.

The Selection viewer to the right of Time range independently shows or hides Warnings, Errors, Succeeded and Unknown transactions. All four are enabled initially; these controls combine with the time and text filters. Unknown controls rows without a diagnostic category.

The transaction list starts with compact 10px text and bold 12px headers so all columns fit more comfortably on screen. View font-size controls remain available; column widths are recalculated for the chosen font.

The sequence-number column and its filter are labeled **SeqNo**.

Table widths are also enforced through physical column tracks and border-box cells, including custom cell templates, to keep the final Possible problem column inside the viewport.

All Python and JavaScript tests, plus their dependency list, are located in `testing/`. Run the commands above from the project root.

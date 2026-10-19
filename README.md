# LogComparator

LogComparator can help identify errors during the rollout of a new TANGO version
in production. By reviewing transaction flows, highlighting possible problems,
and comparing logs, it can support checks that transactions behave as expected
after the upgrade.

LogComparator helps you find and check transactions in TANGO logs. It reads
TANGO log files and PTMS/SPDH and OPN/ISO audit files, brings together the
messages that belong to each transaction, and displays the results in a table.

You can search for a transaction, inspect its complete log, review possible
problems, save its log, or compare it with another transaction.

## Getting started

On Windows, open `dist/LogComparator.exe` or the Desktop shortcut.
The application opens in your browser at `https://127.0.0.1:8080`.
For Docker, use `https://<server-IP>:4020`.

A typical session:

1. Use **File** to import local or remote logs.
2. Choose an available date and a **Bank/Acquirer**.
3. Load the files and wait for the transaction list.
4. Use the filters to find the transactions you need.
5. Select transactions and click **Open**, **Export**, or **Compare**.

## Import local logs

**File > Import local logs** reads files from the computer or server running
LogComparator. If you access it from another computer through a browser,
"local" refers to the server's files, not files on your own computer.

The default Linux folders are:

- `/opt/tango/log`: TANGO logs.
- `/opt/tango/audit`: bank audit files.

To load them:

1. Choose an available day in the calendar.
2. Choose **Import Bank/Acquirer** from the banks available for that day.
3. Click **Load Files**.

The application finds the files for that day automatically. There is no file
or folder picker. It loads and displays the selected bank first, then prepares
the other banks for the same day in the background. This preparation helps
reduce the wait when you switch banks later.

## Import remote logs

**File > Import remote logs (UAT)** reads files from the configured remote
server through SSH. It connects as `j.arvanitis`, then uses `sudo` to access:

- `/opt/tango/MLNPSP01/log`
- `/opt/tango/MLNPSP01/audit`

The dialog connects and lists available days automatically. Choose a day,
choose **Remote Bank/Acquirer**, then click **Read remote logs**.
If listing fails, check the displayed connection message and use
**Retry listing** when it is offered.

As with local import, the selected bank appears first. Other banks for that
day are read and prepared in the background. Today's remote compressed files
are read in memory. Files from earlier days are saved and extracted locally.

## Data and switching banks

**Log folder** and **Audit folder** show the source folders in use.
**Selected date** shows the loaded day and bank.

Use **Bank/Acquirer** to switch banks within the same day. The previous list
clears immediately while the new bank loads. If its results have already been
prepared in the background, the application reuses them. To choose another day,
open the appropriate import dialog again.

The bottom status area shows loading progress, background work, and the numbers
of loaded, visible, and selected transactions.

### Live update

**Live update** starts off and is turned off after each new import. You can
enable it only for today. It updates the list for the selected bank as its
source files change. Other banks are not continuously monitored.
Live update is unavailable for earlier days.

## Understanding the transaction list

Each row represents a transaction or message exchange, such as a LOGON.
Its columns show identifiers, transaction type, amount, response codes, and
any findings from the checks.

| Appearance | Meaning |
| --- | --- |
| Green | Classified as successful. |
| Yellow | A warning needs review. |
| Red | A problem or error was found. |
| No status color | Not classified into one of the above categories. |

**Possible problem** describes the finding. The table shows up to 100 characters;
hover over the field to read the complete description.

Click a column heading to sort the list. Use the controls below the table to
change pages or the number of rows per page.

## Filtering the list

Filters change what is shown; they do not change the original files.
All active filters work together: a transaction must match every active filter.

### Time range

| Field | What it does |
| --- | --- |
| **From** | Sets the start of the time range. |
| **To** | Sets the end, including the whole selected final second. |
| **Timezone** | Sets the timezone used for displayed times and time filtering. |

Click a time field or its calendar icon, choose a date and time, then click
**Apply**. Times use the 24-hour clock.
**From must be before To** means the start is later than the end; correct one
of the two values.

### Selection viewer

Choose which result categories should be visible:

| Option | Shows |
| --- | --- |
| **Warnings** | Transactions with warnings. |
| **Errors** | Transactions with problems or errors. |
| **Succeeded** | Transactions classified as successful. |
| **Unknown** | Transactions without one of the above classifications. |

All four options start enabled. Uncheck a category to hide its rows.
These checkboxes filter the list; they do not select rows for Open or Export.

### Filters: searching individual fields

Enter a complete value or part of it. Searches ignore letter case.
Leave a field empty to stop filtering by that field.

| Filter | What to search for |
| --- | --- |
| **TransUID** | The transaction's unique identifier. |
| **STAN** | The message's trace number. |
| **RRN** | The transaction's retrieval reference number. |
| **AuthCode** | The authorization code. |
| **SeqNo** | The sequence number. |
| **TransactionType** | A type such as purchase, reversal, or LOGON. |
| **TID** | The terminal identifier. |
| **MID** | The merchant identifier. |
| **AMT** | The amount as it appears in the AMT column. |
| **RC_SPDH** | The SPDH response code or its displayed description. |
| **RC_ISO** | The ISO response code or its displayed description. |
| **Possible problem** | Words in the full finding description, including text shortened in the table. |

For example, enter a **TID** and a **TransactionType** to see only matching
transactions from that terminal. For amounts, use the format shown in **AMT**.

**Edit > Clear filters** clears the text filters. Change the time range and
Selection viewer options separately.

## Selecting and opening transactions

Click a row or its first-column checkbox to select or deselect it. Selected
rows have a blue outline and keep their result color. You can select several rows.

- **Open** opens selected transaction logs in separate browser tabs.
  You can also click a **TransUID** or double-click a row to open its log.
- **Download log**, in the transaction tab, saves the complete log.
- **Edit > Select all visible** selects all transactions that pass the filters,
  including those on other table pages.
- **Edit > Clear selection** deselects all rows.

An opened transaction log is a snapshot. It does not refresh automatically when
the main list updates. Right-click a row for **Open**, **Export**, and **Compare**.

## Exporting logs

**Export** saves the selected transactions. If no rows are selected, it saves
all transactions that pass the filters. One transaction downloads as a log file;
several transactions download together in a ZIP file.

The generated logs are also saved in the application's output folder.
Use **File > Settings**, change **Output folder**, and click **Save settings**
to choose that destination. This folder is on the computer or server running
LogComparator, rather than the computer displaying the browser.

### Choosing what the generated logs contain

The controls at the top of the main page apply to logs you open, export, or
compare. The same controls are available under **Tools > Export options**.

| Control | Effect |
| --- | --- |
| **Generated files: SPDH+ISO** | Includes both protocols. |
| **Generated files: ISO** | Includes ISO only. |
| **Generated files: SPDH** | Includes SPDH only. |
| **Byte/Data > Include** | Includes the detailed Byte/Data sections. |
| **Audit blocks > Tango Internal** | Includes internal TANGO audit blocks. |
| **Audit blocks > Tango to Network** | Includes outgoing audit blocks sent to the network. |
| **Audit blocks > Network to Tango** | Includes incoming audit blocks received from the network. |

These settings control the generated log contents. They do not filter table rows.

## Comparing two transactions

Select exactly two transactions and click **Compare**. A separate browser tab
opens with their logs side by side in diff2html. Additions and deletions are
highlighted, and horizontal scrolling is synchronized between the two sides.

- **Previous difference / Next difference** moves between changes.
- **Download diff** saves the differences as a file.

If the generated logs are identical, the page says so.

## Menus and display options

| Menu | Available actions |
| --- | --- |
| **File** | Import local logs, Import remote logs (UAT), Export, and Settings. |
| **Edit** | Clear text filters, select all visible transactions, or clear the selection. |
| **View > Columns / Filters** | Show or hide columns and their corresponding text filters. Hiding a filter also clears its value. Possible problem stays available. |
| **View > Increase / Decrease font size** | Make the transaction list text larger or smaller. |
| **Tools** | Export options and the Open, Export, and Compare actions. |
| **Help > README** | Open this guide in a separate browser tab. |
| **Help > About** | View the application version and author information. |

## HTTPS access

LogComparator serves **HTTPS only**. Use `https://127.0.0.1:8080` on Windows or
`https://<server-IP>:4020` for Docker. Plain HTTP is not served on these ports.

On a Windows source/executable run without configured certificate files, the
application creates a local self-signed certificate in its cache and reuses it
on later starts. For a company-issued certificate, specify both PEM files:

```powershell
.\.venv\Scripts\python.exe main.py --ssl-certfile C:\certs\server.crt --ssl-keyfile C:\certs\server.key
```

The executable accepts the same arguments. You can also set
`LOGCOMPARATOR_SSL_CERTFILE` and `LOGCOMPARATOR_SSL_KEYFILE` instead.
The certificate must match the address used in the browser and its private key.

A self-signed certificate encrypts the connection, but the browser displays a
trust warning. To remove that warning, have the certificate trusted on the client
computer or replace it with a certificate from your company's trusted CA.
Keep the private key on the server. Do not commit certificates or keys to Git.

## Connection messages and closing the application

**Browser <-> LogComparator connection lost** refers to the browser's connection
to the application. **SSH** messages refer to the application's connection to
the remote server. Read the status messages for the affected connection.

Closing a browser tab does not stop the server. On Windows, stop LogComparator
through Task Manager. For a terminal run, use Ctrl+C.

## Installing LogComparator

### Windows: use the ready executable

1. Copy the application to the project folder on the Windows computer.
2. Keep the latest executable at `dist/LogComparator.exe`.
3. Create or keep a Desktop shortcut pointing to that exact file.
4. Run it and wait for the browser to open at `https://127.0.0.1:8080`.

The ready executable includes Python and the browser assets. You do not need
to install Python, Node.js or Docker to use it. If you replace it with a newer
build, stop the running LogComparator process first.

### Windows: install from source

Use this option if you want to run the Python code or build the executable.
You need **Python 3.10 or newer**, **Git for Windows**, and internet access for
the initial dependency installation. Put the project files in the project
folder, open PowerShell there, then run:

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe main.py
```

`setup.ps1` creates the project virtual environment and installs the application
and build dependencies. To choose a specific Python installation:

```powershell
.\setup.ps1 -Python "C:\path\to\python.exe"
```

Use the Windows executable build commands below when you want to produce
`dist/LogComparator.exe`.

### Docker: prerequisites

On the Windows build machine, install Docker Desktop, start it, and select
**Linux containers**. Git must also be available for the version information.
This machine needs internet access to build the image.

The Linux server must already have Docker Engine and the Docker Compose plugin.
Check them with:

```sh
sudo docker --version
sudo docker compose version
```

If they are not installed, arrange their offline installation with the server
administrator before deploying LogComparator. The application image does not
install Docker itself. You do not need Python or Git on the Linux server when
running the transferred image.

## Docker

### First deployment: configure the server

Put the Compose files in the project directory on the Docker host.
For a first deployment, create `.env` from the supplied example:

```sh
cp .env.docker.example .env
```

Edit `.env` for that server:

```dotenv
LOGCOMPARATOR_PORT=4020
LOGCOMPARATOR_TLS_DIR=./certs
TANGO_LOG_DIR=/opt/tango/log
TANGO_AUDIT_DIR=/opt/tango/audit
TANGO_READ_GID=10001
```

The two source values must point to folders that actually exist on the **Linux
host**. For example, if the files are under `/opt/tango/MLNPSP01/log` and
`/opt/tango/MLNPSP01/audit`, use those values instead. Inside the container,
they will still appear at `/opt/tango/log` and `/opt/tango/audit`.

Set `TANGO_READ_GID` to an existing group with permission to read the source
files and access their directories. The container runs as user `10001`, with
that group added. Keep an existing server `.env` when updating the application.

If Linux has **no internet**, continue with **Build on Windows and run on Linux
without internet** below. Do not run a build on that server.

For a Docker host **with internet**, build and start from the project directory:

```sh
sudo docker compose build
```

Create the HTTPS certificate as described below, then start with
`sudo docker compose up -d --no-build --pull never`.

Open `https://<server-IP>:4020`. The default mapping is host **4020** to container
**8080**. `LOGCOMPARATOR_PORT` changes the external port.

| Setting | Default |
| --- | --- |
| `TANGO_LOG_DIR` | `/opt/tango/log` on the host |
| `TANGO_AUDIT_DIR` | `/opt/tango/audit` on the host |
| `TANGO_READ_GID` | `10001`; set an existing group that can read both source directories |

The sources are mounted read-only at `/opt/tango/log` and `/opt/tango/audit`
inside the container. Exports, cache and state use named volumes.

For a host without local Tango directories, use remote import mode:

```sh
sudo docker compose -f compose.remote.yaml build
sudo docker compose -f compose.remote.yaml up -d --no-build --pull never
```

Use the same Compose file for subsequent operations in that mode.

### Docker HTTPS certificate (first installation)

Both Compose modes mount the certificate folder read-only at `/data/tls`.
Set `LOGCOMPARATOR_TLS_DIR` in `.env` if it is not the default `./certs`.
The folder must contain `server.crt` and `server.key`, readable by container
user `10001`. Certificates are kept outside the image so an update preserves them.

After building or loading `logcomparator:local`, create a temporary self-signed
certificate on Linux. These commands use Python already inside the image and
need no internet access or additional Linux packages:

```sh
sudo mkdir -p certs
sudo chown 10001:10001 certs
sudo chmod 700 certs
sudo docker run --rm --network none --mount "type=bind,source=$(pwd)/certs,target=/certs" --entrypoint python logcomparator:local create_https_certificate.py --host 10.1.110.84 --output /certs
```

Use your server's actual IP or DNS name in `--host`; repeat the option to include
more addresses. The generated certificate also includes `localhost` and
`127.0.0.1`, and is valid for 365 days. The generator refuses to overwrite existing
certificate files. Reuse them for updates; arrange replacement before expiry.
If you already have a company-issued certificate, place it and its matching key
in this folder instead of running the generator.

### Build on Windows and run on Linux without internet

Use this procedure when the Linux server has no internet access. Build the
complete image on Windows, where Docker can download dependencies, then transfer
it to Linux. Linux does not need to download Python, application dependencies,
or a base image. Docker Engine and Docker Compose must already be installed there.

**1. Build the image on Windows.**

Start Docker Desktop in **Linux containers** mode. Open PowerShell in the project
folder, using the version of the code you want to deploy:

```powershell
cd C:\Users\j.arvanitis\Desktop\Tango\github\LogComparator
docker build --platform linux/amd64 --build-arg BUILD_DESCRIBE="$(git describe --tags --always --dirty)" --build-arg BUILD_GIT_HASH="$(git rev-parse --short=12 HEAD)" -t logcomparator:local .
```

This command builds the application and includes its Python dependencies,
browser assets and README. The Windows machine needs internet access for any
base image or dependencies that are not already cached. `linux/amd64` targets
an Intel/AMD 64-bit server; use `linux/arm64` for an ARM64 server.

Check the image before transferring it:

```powershell
docker run --rm --network none --entrypoint python logcomparator:local -c "import main, web_app, web_services, source_memory; import log_config; print(log_config.APP_BUILD_DESCRIBE)"
```

The command must finish without an import error and print the expected version.
Then save the complete image:

```powershell
docker save -o logcomparator.tar logcomparator:local
```

**2. Transfer the files to Linux.**

Copy these files to the project directory on the server, using SFTP/SCP or your
usual transfer tool. Connect as `j.arvanitis`:

- `logcomparator.tar`: the image built above.
- `compose.yaml` and `compose.remote.yaml`: the current deployment settings.
- The certificate generator is included in the image; keep the server certificate folder on Linux.
- `README.md`: this guide, if you want a copy outside the image.

Keep the server's existing `.env`. It contains that server's port, source folders
and read-access group. For a first deployment only, also transfer
`.env.docker.example`, copy it to `.env`, and set those values for the server.
Do not replace an existing `.env` with the example.

**3. Load and start the image on Linux.**

Log in as `j.arvanitis`, then use `sudo` for Docker commands. From the directory
containing the Compose files and `.env`:

```sh
cd /home/j.arvanitis/projects/LogComparator
sudo docker load -i logcomparator.tar
# First installation: create the HTTPS certificate using the section above.
# Updates: reuse the existing certificate folder.
sudo docker compose up -d --no-build --pull never --force-recreate
```

`docker load` imports the image from the transferred file. `--no-build` prevents
a build on Linux, and `--pull never` prevents an image download.
No `pip install`, `docker pull`, or source-code download is needed on Linux.

If the server has no local Tango folders and you use remote import only, replace
the last command with:

```sh
sudo docker compose -f compose.remote.yaml up -d --no-build --pull never --force-recreate
```

Use the same Compose file for later status, log and update commands.
Recreating the container preserves its existing data volumes.

**4. Check that the application is ready.**

```sh
sudo docker compose ps
sudo docker compose logs --tail=100 logcomparator
sudo curl --fail --cacert certs/server.crt https://127.0.0.1:4020/health
```

Allow a few seconds for startup, then repeat the health check if needed.
Once it responds, open `https://10.1.110.84:4020/` for this server, or
`https://<server-IP>:4020/` for another server. Use Ctrl+F5 to reload an existing
browser tab. Check **Help > About** to confirm the deployed version.

For the next update, repeat the same build, save, transfer, load and recreate
steps. The `.tar` file must come from the new build; loading an old archive
will restore the old application.

### Check the service

```sh
docker compose ps
docker compose logs --tail=100 logcomparator
sudo curl --fail --cacert certs/server.crt https://127.0.0.1:4020/health
```

Wait for `/health` to respond before opening the page. A container repeatedly
restarting indicates an application startup failure. Rebuild the image if
its logs report a missing application module.

## Configuration

Source runs support `LOGCOMPARATOR_LOG_DIR`, `LOGCOMPARATOR_AUDIT_DIR`,
`LOGCOMPARATOR_OUTPUT` and `LOGCOMPARATOR_CACHE`. **File > Settings** changes
the export destination. **Tools > Export options** controls included protocols,
byte data and audit directions.

The UI has no login; use it on a trusted internal network.
Windows diagnostics are in `%LOCALAPPDATA%\LogComparator\LogComparator.log`.

## Build the Windows executable

Run from the project root with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe update_build_info.py
.\.venv\Scripts\pyinstaller.exe --onefile --name LogComparator --add-data "build_info.json;." main.py
```

Publish the result at `dist/LogComparator.exe`. Keep the Desktop shortcut
pointing to that path.

## Creating a release

Create releases from the Windows project folder after setup has installed the
build tools. You need Git access to `origin`, including permission to push tags.

**1. Prepare the version you want to publish.**

Run the tests, review your changes, then commit the intended source and README
changes. Include any new application files in that commit. Check the working
tree and push the commit:

```powershell
git status --short
git push origin HEAD
```

The release script requires committed source files. Generated build outputs
may remain modified. Do not include credentials, `.env`, or image archives
in your commit.

**2. Create the release tag and build the executable.**

```powershell
.\.venv\Scripts\python.exe .\create_release.py
```

The script:

1. Fetches release tags from `origin`.
2. Chooses the next version and creates an annotated Git tag.
3. Pushes that tag to `origin`.
4. Updates the version information and builds the Windows executable.
5. Publishes the executable at `dist/LogComparator.exe`.

Version numbers advance automatically. For example, `v1.1.28` becomes
`v1.1.29`; the following release becomes `v1.2.1`. If the current commit already
has an annotated release tag, the script reuses it.

This publishes a **Git release tag** and produces the local executable. It does
not create a GitHub Release page, upload executable assets, build a Docker
image, or update the Linux server.

**3. Check the result and distribute it.**

Reopen `dist/LogComparator.exe` and check **Help > About**. Distribute that
executable to Windows users. Keep the Desktop shortcut pointing to the fixed
`dist/LogComparator.exe` path.

For Docker, follow **Build on Windows and run on Linux without internet** above
from the same tagged version. Build and save a new `logcomparator.tar`, then
transfer and load it on Linux. The Windows executable and Docker image are
separate builds.

### Rebuild without creating a release

To rebuild the executable without creating or pushing a tag:

```powershell
.\build_executable.ps1
```

The equivalent command is:

```powershell
.\.venv\Scripts\python.exe .\create_release.py --build-only
```

The tag is published before the executable build starts. If that build fails,
the published tag remains. Fix the build problem and use the build-only command
to retry; a new release tag is not needed.

## Tests

All tests and their dependency list are in `testing/`. Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r testing/requirements-web-test.txt
.\.venv\Scripts\python.exe -m pytest testing -q
node testing/test_diff2html.js
node testing/test_table_sizing.js
```

## Command-line analysis

```powershell
.\.venv\Scripts\python.exe main.py audit.file1 audit.file2 --stan 123456 --rrn 000358000879 --authcode A1B2C3 -o C:\path\to\output
```

param(
    [string]$Server = '10.1.110.84',
    [int]$SshPort = 22,
    [string]$RemoteDirectory = '/home/j.arvanitis/projects/LogComparator',
    [switch]$RemoteOnly,
    [switch]$SkipBuild,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$RemoteUser = 'j.arvanitis'
$SshPassword = '__DEPLOY_PASSWORD__'
$ImageName = 'logcomparator_iarv:latest'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Project virtual environment not found. Run setup.ps1 first.'
}
if ($SshPassword -eq '__DEPLOY_PASSWORD__' -or [string]::IsNullOrEmpty($SshPassword)) {
    throw 'Set the SSH/sudo password in your local deploy_docker.ps1.'
}
$composeFile = if ($RemoteOnly) { 'compose.remote.yaml' } else { 'compose.yaml' }
# The existing project SSH/SCP libraries are embedded here; no separate .py file is needed.
# The credential stays out of command arguments, logs, Git and the Docker image.
$remoteCode = @'
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import sys
import time
import uuid
from scp import SCPClient
from remote_logs import RemoteConnection, connect
IMAGE = 'logcomparator_iarv:latest'
SUPPORT_FILES = ('compose.yaml', 'compose.remote.yaml', 'README.md', '.env.docker.example')
def remote_directory(value):
    path = PurePosixPath(value)
    if (not path.is_absolute() or '..' in path.parts or len(path.parts) < 3
            or any(character in value for character in '\x00\r\n')):
        raise ValueError('Use an absolute project directory, not / or a parent directory.')
    return str(path)

def ssh_command(client, command, *, password=None, echo=False):
    if password is not None:
        command = 'sudo -S -p "" -- sh -c ' + shlex.quote(command)
    stdin, stdout, stderr = client.exec_command(command, timeout=180)
    if password is not None:
        stdin.write(password + '\n')
        stdin.flush()
    channel = stdout.channel
    channel.shutdown_write()
    output, errors = [], []
    while True:
        for ready, receive, target in ((channel.recv_ready, channel.recv, output),
                                       (channel.recv_stderr_ready, channel.recv_stderr, errors)):
            while ready():
                text = receive(65536).decode('utf-8', errors='replace')
                target.append(text)
                if echo:
                    print(text, end='', flush=True)
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            break
        time.sleep(0.05)
    status = channel.recv_exit_status()
    stdin.close()
    stdout.close()
    stderr.close()
    if status:
        raise RuntimeError(''.join(errors).strip() or ''.join(output).strip()
                           or f'Remote command failed (exit {status}).')
    return ''.join(output)

def archive_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def install_command(stage, destination, compose_file):
    destination = remote_directory(destination)
    suffix = uuid.uuid4().hex
    commands = ['set -eu', 'cd ' + shlex.quote(destination), 'test -f .env']
    for name in ('logcomparator.tar', *SUPPORT_FILES):
        source = shlex.quote(str(PurePosixPath(stage) / name))
        temporary = shlex.quote(f'.{name}.{suffix}.tmp')
        target = shlex.quote(name)
        mode = '600' if name.endswith('.tar') else '644'
        commands += [f'install -m {mode} -- {source} {temporary}',
                     f'mv -f -- {temporary} {target}']
    compose = 'docker compose -f ' + shlex.quote(compose_file)
    commands += [compose + ' config --quiet',
                 'docker load -i logcomparator.tar',
                 'docker image inspect ' + shlex.quote(IMAGE) + ' >/dev/null',
                 compose + ' up -d --no-build --pull never --force-recreate logcomparator']
    return '\n'.join(commands)

def upload_and_install(client, connection, archive, destination, compose_file):
    stage = ssh_command(client, 'mktemp -d /tmp/logcomparator-deploy.XXXXXX').strip()
    stage_path = PurePosixPath(stage)
    if stage_path.parent != PurePosixPath('/tmp') or not stage_path.name.startswith('logcomparator-deploy.'):
        raise RuntimeError('Invalid remote staging directory.')
    files = [archive, *(ROOT / name for name in SUPPORT_FILES)]
    percentages = {}

    def progress(filename, size, sent):
        name = Path(filename.decode() if isinstance(filename, bytes) else filename).name
        percent = int(sent * 100 / size) if size else 100
        if percent >= percentages.get(name, -10) + 10 or percent == 100 and percentages.get(name) != 100:
            percentages[name] = percent
            print(f'  SCP {name}: {percent}%', flush=True)

    try:
        with SCPClient(client.get_transport(), socket_timeout=120, progress=progress) as scp:
            for path in files:
                scp.put(str(path), remote_path=str(stage_path / path.name))
        remote_hash = ssh_command(client, 'sha256sum -- ' + shlex.quote(str(stage_path / archive.name)))
        if not remote_hash.split() or remote_hash.split()[0] != archive_digest(archive):
            raise RuntimeError('Archive checksum mismatch; the server has not been updated.')
        print('[5/6] Loading the image and recreating logComparator...', flush=True)
        ssh_command(client, install_command(stage, destination, compose_file),
                    password=connection.sudo_password, echo=True)
    finally:
        # Remove only this run's known staging files, never project data.
        paths = ' '.join(shlex.quote(str(stage_path / path.name)) for path in files)
        try:
            ssh_command(client, f'rm -f -- {paths}; rmdir -- {shlex.quote(stage)}')
        except Exception as error:
            print(f'Could not clean temporary transfer directory {stage}: {error}', file=sys.stderr)

def wait_for_health(client, connection, timeout=120):
    command = ('docker exec logComparator python -c '
               + shlex.quote('from web_tls import check_health; print(check_health().decode())'))
    deadline = time.monotonic() + timeout
    last_error = ''
    while time.monotonic() < deadline:
        try:
            result = json.loads(ssh_command(client, command, password=connection.sudo_password))
            if result.get('app') != 'LogComparator':
                raise ValueError('Unexpected health response.')
            return result
        except (RuntimeError, ValueError) as error:
            last_error = str(error)
            time.sleep(2)
    raise RuntimeError('The container did not pass its HTTPS health check: ' + last_error)

parser = argparse.ArgumentParser()
parser.add_argument('--phase', choices=('check', 'deploy'), required=True)
parser.add_argument('--project-root', required=True)
parser.add_argument('--server', required=True)
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--user', required=True)
parser.add_argument('--remote-dir', required=True)
parser.add_argument('--compose', choices=('compose.yaml','compose.remote.yaml'), required=True)
args = parser.parse_args()
ROOT = Path(args.project_root).resolve()
try:
    destination = remote_directory(args.remote_dir)
    password = os.environ['LOGCOMPARATOR_DEPLOY_PASSWORD']
    server = '[' + args.server + ']' if ':' in args.server else args.server
    connection = RemoteConnection(server + ':' + str(args.port), args.user, password,
                                  allow_keys=True, auto_accept_host=True, use_sudo=True,
                                  sudo_password=password)
    with connect(connection) as client:
        client.get_transport().set_keepalive(30)
        preflight = ('set -eu\ncd ' + shlex.quote(destination)
                     + '\nif ! test -f .env; then echo "Configure the server .env before deployment." >&2; exit 1; fi'
                     + '\ndocker compose version\ndocker info --format '+shlex.quote('{{.ServerVersion}}')+'\ncommand -v sha256sum >/dev/null')
        ssh_command(client, preflight, password=password, echo=True)
        if args.phase == 'check':
            print('Deployment preflight passed.')
        else:
            archive = ROOT / 'logcomparator.tar'
            if not archive.is_file() or not archive.stat().st_size:
                raise ValueError('logcomparator.tar is missing or empty.')
            print('[4/6] Transferring the archive and Compose files with SCP...', flush=True)
            upload_and_install(client, connection, archive, destination, args.compose)
            print('[6/6] Waiting for the HTTPS health check...', flush=True)
            result = wait_for_health(client, connection)
            print('Deployment complete. Version: ' + result.get('version', 'unknown'))
            print('Remote archive: ' + str(PurePosixPath(destination) / archive.name))
except Exception as error:
    print('Deployment failed: ' + str(error), file=sys.stderr)
    raise SystemExit(1)

'@

function Invoke-RemotePhase([string]$Phase) {
    $remoteArguments = @('-', '--phase', $Phase,
        '--project-root', $PSScriptRoot, '--server', $Server, '--port', $SshPort,
        '--user', $RemoteUser, '--remote-dir', $RemoteDirectory, '--compose', $composeFile)
    $previousPassword = [Environment]::GetEnvironmentVariable('LOGCOMPARATOR_DEPLOY_PASSWORD', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('LOGCOMPARATOR_DEPLOY_PASSWORD', $SshPassword, 'Process')
        $remoteCode | & $projectPython @remoteArguments
        if ($LASTEXITCODE -ne 0) { throw "Remote deployment failed (exit $LASTEXITCODE)." }
    } finally {
        [Environment]::SetEnvironmentVariable('LOGCOMPARATOR_DEPLOY_PASSWORD', $previousPassword, 'Process')
    }
}

Push-Location $PSScriptRoot
try {
    Write-Output "[1/6] Checking $RemoteUser@$Server..."
    Invoke-RemotePhase 'check'
    if (-not $CheckOnly) {
        if (-not $SkipBuild) {
            Write-Output "[2/6] Building $ImageName..."
            $buildDescribe = & git describe --tags --always --dirty
            if ($LASTEXITCODE -ne 0) { throw 'Could not read the Git version.' }
            $buildGitHash = & git rev-parse --short=12 HEAD
            if ($LASTEXITCODE -ne 0) { throw 'Could not read the Git commit.' }
            & docker build --platform linux/amd64 --build-arg "BUILD_DESCRIBE=$buildDescribe" --build-arg "BUILD_GIT_HASH=$buildGitHash" -t $ImageName .
            if ($LASTEXITCODE -ne 0) { throw 'Docker build failed. The server was not updated.' }
        } else {
            Write-Output "[2/6] Reusing $ImageName..."
        }
        & docker image inspect $ImageName --format '{{.Id}}'
        if ($LASTEXITCODE -ne 0) { throw 'The latest image does not exist locally.' }
        Write-Output '[3/6] Creating logcomparator.tar...'
        $temporaryArchive = Join-Path $PSScriptRoot ('.docker-export-' + [guid]::NewGuid().ToString('N') + '.tar')
        try {
            & docker save -o $temporaryArchive $ImageName
            if ($LASTEXITCODE -ne 0) { throw 'Docker save failed. The server was not updated.' }
            if ((Get-Item -LiteralPath $temporaryArchive).Length -eq 0) { throw 'Docker created an empty archive.' }
            Move-Item -LiteralPath $temporaryArchive -Destination (Join-Path $PSScriptRoot 'logcomparator.tar') -Force
        } finally {
            if (Test-Path -LiteralPath $temporaryArchive) { Remove-Item -LiteralPath $temporaryArchive -Force }
        }
        Invoke-RemotePhase 'deploy'
    }
} finally {
    Pop-Location
}

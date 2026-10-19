FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    LOGCOMPARATOR_SSL_CERTFILE=/data/tls/server.crt \
    LOGCOMPARATOR_SSL_KEYFILE=/data/tls/server.key \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LOGCOMPARATOR_LOG_DIR=/opt/tango/log \
    LOGCOMPARATOR_AUDIT_DIR=/opt/tango/audit \
    LOGCOMPARATOR_OUTPUT=/data/exports \
    LOGCOMPARATOR_CACHE=/data/cache \
    NICEGUI_STORAGE_PATH=/data/state \
    HOME=/data

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY logcomparator_ui/ ./logcomparator_ui/
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY main.py windows_runtime.py web_app.py web_services.py gui_services.py remote_logs.py log_config.py log_core.py source_memory.py web_tls.py create_https_certificate.py README.md ./
COPY diagnostic_common.py transaction_checks.py iso_checks.py spdh_checks.py tango_checks.py emv_checks.py ./

ARG BUILD_DESCRIBE=container
ARG BUILD_GIT_HASH=unknown
RUN python -c "import json,os; from pathlib import Path; Path('build_info.json').write_text(json.dumps({'build_describe':os.environ['BUILD_DESCRIBE'],'release_tag':'container','git_hash':os.environ['BUILD_GIT_HASH'],'git_dirty':False})); paths=['/data/exports','/data/cache','/data/state','/data/cache/local','/data/cache/local/log','/data/cache/local/audit']; [Path(p).mkdir(parents=True, exist_ok=True) for p in paths]; [os.chown(p,10001,10001) for p in ['/data',*paths]]"

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "web_tls.py"]
ENTRYPOINT ["python", "main.py"]
CMD ["--no-browser", "--port", "8080"]

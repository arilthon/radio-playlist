FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RADIO_DATA_DIR=/data \
    DASHBOARD_BIND_HOST=0.0.0.0 \
    OAUTH_BIND_HOST=0.0.0.0

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 radio \
    && useradd --uid 10001 --gid radio --create-home radio \
    && mkdir -p /data \
    && chown radio:radio /data

COPY *.py dashboard.html ./
USER radio
EXPOSE 8090 8080 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/', timeout=3).close()"
CMD ["python", "dashboard.py"]

FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates ffmpeg tzdata libstdc++6 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip check
COPY app ./app
COPY assets ./assets
COPY scripts ./scripts
# Public, secret-free defaults only. config.json/.env are NOT baked into the image.
COPY config.example.json ./config.example.json
RUN mkdir -p /app/data/logs && chown -R app:app /app/data
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5 \
    CMD python -c "import os,urllib.request; p=os.getenv('PORT', os.getenv('HTTP_PORT','8080')); urllib.request.urlopen('http://127.0.0.1:'+p+'/health/ready', timeout=3)" || exit 1
CMD ["python", "-m", "app"]

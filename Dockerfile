FROM python:3.14-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 renamely \
    && useradd --system --uid 1000 --gid renamely --home-dir /app --shell /usr/sbin/nologin renamely \
    && mkdir -p /app/input /app/output

WORKDIR /app

COPY pyproject.toml script.py ./
RUN pip install --no-cache-dir --no-compile --root-user-action=ignore .

COPY entrypoint.sh ./
RUN chmod 0755 script.py entrypoint.sh \
    && chown -R renamely:renamely /app/input /app/output /app/script.py

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["cron", "-f"]

FROM ghcr.io/jhunufernandes/cronos:latest

# Command the cron schedule runs (cronos requires COMMAND; overridable at runtime).
ENV COMMAND="python /app/main.py"

COPY pyproject.toml main.py ./
RUN pip install --no-cache-dir --no-compile --root-user-action=ignore .

COPY prestart.sh /app/prestart.sh
RUN chmod 0755 /app/prestart.sh \
    && mkdir -p /app/input /app/output \
    && chown -R app:app /app/input /app/output /app/main.py /app/prestart.sh

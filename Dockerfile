FROM python:3.11-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

ENV PORT=9090
ENV FAIL_MODE=false
ENV APP_VERSION=1.0.0

EXPOSE 9090

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:9090/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:9090", "--workers", "2", "--timeout", "120", "main:app"]

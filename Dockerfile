FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN python -m venv .venv
COPY requirements.txt ./
RUN .venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY . .
CMD ["/app/.venv/bin/python", "main.py"]

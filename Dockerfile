FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN addgroup --system agrilink && adduser --system --ingroup agrilink agrilink
WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist
RUN chmod +x /app/backend/entrypoint.sh \
    && mkdir -p /var/data/agrilink/uploads \
    && chown -R agrilink:agrilink /app /var/data/agrilink

USER agrilink
EXPOSE 10000

CMD ["./entrypoint.sh"]

FROM python:3.13-slim AS backend-deps
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM backend-deps AS backend-dev-deps
COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

FROM backend-dev-deps AS backend-e2e-deps
# Install Node.js 22 (for Vite dev server) and Playwright system deps
RUN apt-get update && apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN playwright install --with-deps chromium

FROM node:22-slim AS frontend-deps
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci

FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS prod
WORKDIR /app

COPY --from=backend-deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-deps /usr/local/bin /usr/local/bin
COPY backend/ ./
COPY --from=frontend-build /frontend/dist ./static
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ENV DATABASE_URL=""
EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]

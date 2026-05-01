FROM python:3.13-slim AS backend-deps
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM backend-deps AS backend-dev-deps
COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

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

FROM python:3.13-slim
WORKDIR /app

COPY --from=backend-deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-deps /usr/local/bin /usr/local/bin
COPY backend/ ./
COPY --from=frontend-build /frontend/dist ./static

ENV DATABASE_URL=""
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

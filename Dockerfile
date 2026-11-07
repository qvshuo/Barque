FROM node:26.13.0-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --global npm@12.2.2 && npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.15.2-alpine
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BARQUE_DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip==26.3 \
    && pip install --no-cache-dir -r requirements.txt \
    && mkdir -p data
COPY app ./app
COPY frontend/SHADCN-LICENSE ./frontend/SHADCN-LICENSE
COPY --from=frontend /build/dist ./frontend/dist
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/auth/session', timeout=3)"
CMD ["python", "-m", "app.main"]

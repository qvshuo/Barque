FROM python:3.15.2-alpine
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BARQUE_DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip==26.3 \
    && pip install --no-cache-dir -r requirements.txt \
    && addgroup -S -g 10001 barque && adduser -S -u 10001 -G barque barque \
    && mkdir -p data && chown barque:barque data
COPY app ./app
USER barque:barque
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/auth/session', timeout=3)"
CMD ["python", "-m", "app.main"]

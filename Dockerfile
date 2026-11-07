FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BD2_DATA_DIR=/data

WORKDIR /app

# Solo dependencias de ejecución: se omiten pytest, matplotlib y psycopg2 (tests y benchmarks).
# opencv-python-headless evita las librerías gráficas del sistema.
COPY requirements.txt .
RUN grep -v -E '^(pytest|matplotlib|psycopg2-binary)' requirements.txt \
      | sed 's/^opencv-python>=/opencv-python-headless>=/' > /tmp/req.txt \
    && pip install --default-timeout=120 --retries=10 -r /tmp/req.txt

COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]

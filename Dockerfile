FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir '.[server]' && useradd --uid 10001 --create-home bolsa && mkdir /data && chown bolsa /data
USER bolsa
ENV BA_DATA_DIR=/data
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "60", "bolsa_abierta.wsgi:app"]

FROM python:3.11-slim

WORKDIR /app

# Dependencies before the code: a code change does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shortener.py .
COPY data ./data

# Listen on all interfaces, so that the published port reaches the service,
# and keep the mappings in /app/data, where Compose and Kubernetes mount a
# volume. The public key is mounted at /app/keys; it is not part of the image.
ENV HOST=0.0.0.0 PORT=5000 DATA_DIR=/app/data PYTHONUNBUFFERED=1
EXPOSE 5000

CMD ["python", "shortener.py"]

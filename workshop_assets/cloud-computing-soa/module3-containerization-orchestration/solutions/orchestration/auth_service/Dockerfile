FROM python:3.11-slim

WORKDIR /app

# Dependencies before the code: a code change does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY auth.py .
COPY data ./data

# Listen on all interfaces, so that the published port reaches the service,
# and keep the accounts in /app/data, where Compose and Kubernetes mount a
# volume. The keys are mounted at /app/keys; they are not part of the image.
ENV HOST=0.0.0.0 PORT=5001 DATA_DIR=/app/data PYTHONUNBUFFERED=1
EXPOSE 5001

CMD ["python", "auth.py"]

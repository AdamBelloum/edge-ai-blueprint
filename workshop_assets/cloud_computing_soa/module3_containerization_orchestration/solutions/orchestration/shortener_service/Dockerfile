FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shortener.py .
COPY data ./data

EXPOSE 5000

CMD ["python", "shortener.py"]
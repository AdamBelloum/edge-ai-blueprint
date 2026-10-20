# URL-shortener image: build and start both services with:
#   docker compose up --build -d
# Run from the parent containerization directory after preparing local keys.
# Python 3.11 slim provides the runtime with fewer bundled system tools.
FROM python:3.11-slim

# Subsequent commands and the running application use /app.
WORKDIR /app

# Copy dependencies first so code-only edits can reuse the installation
# layer when the dependency file and preceding inputs remain unchanged.
COPY requirements.txt .
# Install pinned dependencies without retaining pip download caches.
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the service implementation rather than the entire host directory.
COPY shortener.py .
# Include initial data; Compose mounts persistent URL storage at /app/data.
# Rebuilding the image does not replace existing volume contents.
COPY data ./data

# Document container port 5000; this instruction does not publish a host port.
# Host access is configured by the Compose ports setting.
EXPOSE 5000

# Start the application when the container runs, not during the build.
# Compose mounts the public verification key; never give this service
# the authentication private signing key.
CMD ["python", "shortener.py"]

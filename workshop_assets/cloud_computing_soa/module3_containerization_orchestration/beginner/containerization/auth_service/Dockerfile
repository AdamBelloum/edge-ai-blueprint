# Authentication image: build and start with docker compose up --build -d auth.
# Run that command from the parent containerization directory.
# Prepare local keys first using setup_local_keys.sh.
# Python 3.11 slim provides the runtime with fewer bundled system tools.
FROM python:3.11-slim

# Subsequent commands and the running application use /app.
WORKDIR /app

# Copy dependencies before application code so code-only edits can reuse
# the dependency-installation layer when its inputs remain unchanged.
COPY requirements.txt .
# Install pinned dependencies; omit pip download caches from the image.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the service implementation, not the entire host directory.
COPY auth.py .
# Include initial data. Compose mounts persistent storage at /app/data.
# Existing volume contents are not replaced by rebuilding this image.
COPY data ./data

# Document the container port; EXPOSE does not publish it on the host.
# The Compose ports setting provides host access.
EXPOSE 5001

# Start the service when the container runs, not while the image builds.
# Signing keys are supplied through the Compose key mount, not this image.
# This practical uses the Flask development server, not production hosting.
CMD ["python", "auth.py"]

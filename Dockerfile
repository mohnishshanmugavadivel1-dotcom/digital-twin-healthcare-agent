# Stage 1: Build the LIVE React Frontend (NOT the 2-patient static snapshot!)
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python FastAPI Backend + All 12 Test Patients + Live Twin Engine
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Copy Python project & install
COPY pyproject.toml requirements.lock README.md LICENSE ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY reports/ ./reports/
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps -e .

# Copy the built live React frontend into frontend/dist where FastAPI serves it
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Pre-generate the 60-patient synthetic cohort and train the model bundle at image build time
# (~45 seconds during Docker build so the live server boots in 1 second with ALL 12 test patients!)
RUN glucotwin generate && glucotwin train

# Hugging Face Spaces uses port 7860 by default; Render uses $PORT
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "glucotwin serve --host 0.0.0.0 --port ${PORT:-7860}"]

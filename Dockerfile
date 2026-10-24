# Stage 1: Build the React frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend & Final Production Image
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies required for scientific/ML packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy Python configuration and source code
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY reports/ ./reports/

# Install the glucotwin package and its dependencies
RUN pip install --no-cache-dir -e .

# Generate the synthetic patient cohort and train the ML models during image build
RUN glucotwin train && python3 scripts/b23_joint_support_analysis.py

# Copy the compiled React frontend from Stage 1 into the folder FastAPI serves
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Hugging Face Spaces requires containers to listen on port 7860
ENV GLUCOTWIN_HOST=0.0.0.0
ENV GLUCOTWIN_PORT=7860
EXPOSE 7860

# Start the FastAPI server
CMD ["glucotwin", "serve", "--host", "0.0.0.0", "--port", "7860"]

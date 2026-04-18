# ============================================================
# Stage 1: Build the React frontend
# ============================================================
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend

# Install dependencies first (cached layer if package.json unchanged)
COPY frontend/package*.json ./
RUN npm ci

# Copy source and build
COPY frontend/ ./
RUN npm run build
# Output is in /app/frontend/dist


# ============================================================
# Stage 2: Python backend runtime
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy your entire backend (which includes src/)
COPY backend/ ./

# Copy the built React files into backend/static/
# FastAPI's StaticFiles will serve them from there
COPY --from=frontend-build /app/frontend/dist ./static

# Cloud Run sets PORT environment variable (default 8080)
ENV PORT=8080

# Start the FastAPI server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
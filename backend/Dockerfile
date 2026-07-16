FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code + data(템플릿/패턴 read-only 베이크 — 생성 시 참조)
COPY app/ ./app/
COPY data/ ./data/

# Cloud Run은 $PORT(기본 8080) 주입. Render 등은 8000. 둘 다 대응.
ENV PORT=8080
EXPOSE 8080

# uvicorn 단일 프로세스(내부 ProcessPoolExecutor가 RL/생성 병렬, --cpu 코어 수 따라감).
# CORS는 CORS_ORIGINS env로 프론트 origin 허용.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}

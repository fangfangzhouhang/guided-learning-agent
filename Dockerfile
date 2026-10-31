FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
COPY content ./content

# Pass your key at runtime:  docker run -e LLM_API_KEY=... -p 8000:8000 gla
# Without a key the agent runs in offline guided mode.
ENV LLM_BASE_URL=https://api.deepseek.com/v1 \
    LLM_MODEL=deepseek-chat
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

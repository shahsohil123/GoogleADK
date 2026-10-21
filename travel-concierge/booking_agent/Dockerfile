FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

CMD ["sh", "-c", "uvicorn booking_langgraph_agent.agent:app --host 0.0.0.0 --port ${PORT:-8080}"]

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "uvicorn trip_planning_agent.a2a_app:app --host 0.0.0.0 --port ${PORT:-8080}"]

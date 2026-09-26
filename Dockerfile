FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 2 app:app
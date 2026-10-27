FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

EXPOSE 8000

# Watchdog (watchmedo) перезапускает uvicorn при правках .py.
# --debug-force-polling нужен для bind-mount с Windows / Docker Desktop.
CMD ["watchmedo", "auto-restart", \
     "--directory=/app", \
     "--pattern=*.py", \
     "--recursive", \
     "--debug-force-polling", \
     "--interval=1", \
     "--ignore-patterns=*/__pycache__/*;*.pyc", \
     "--", \
     "uvicorn", "crm:app", "--host", "0.0.0.0", "--port", "8000"]

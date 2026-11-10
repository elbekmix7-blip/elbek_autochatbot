FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y gcc libc6-dev \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY main.py .

EXPOSE 7860
CMD ["python", "-u", "main.py"]

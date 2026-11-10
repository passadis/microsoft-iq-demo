# Build from the repo root:  docker build -f webapp/Dockerfile -t iq-demo-web .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libltdl7 libkrb5-3 libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY webapp/requirements.txt webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt

COPY scripts/ scripts/
COPY demo-prompts.txt demo-prompts.txt
COPY webapp/ webapp/

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT}"]

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY garmin_bridge_email.py garmin_sender.py . 

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/garmin_bridge_email.py"]

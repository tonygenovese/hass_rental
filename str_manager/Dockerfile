ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.11
FROM $BUILD_FROM

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]

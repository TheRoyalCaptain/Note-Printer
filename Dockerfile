FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends cups cups-client cups-filters printer-driver-dymo fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py entrypoint.sh ./
COPY storage.py ./
COPY templates ./templates
COPY static ./static
RUN chmod +x entrypoint.sh
EXPOSE 8080
CMD ["./entrypoint.sh"]

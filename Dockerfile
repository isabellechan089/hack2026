# TrialTrace / Evidence Atlas -- one container, no build step.
#   docker build -t trialtrace .
#   docker run --rm -p 8000:8000 --env-file .env trialtrace
# Saved cohorts and demo snapshots ship in the image, so the design view and
# both integrity demos answer with no network. Live lookups need outbound HTTPS.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p .cache
EXPOSE 8000
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.13.7-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --gid 1000 app && adduser --uid 1000 --gid 1000 --disabled-password app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "speakable.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir fastapi==0.141.1 uvicorn==0.52.1 httpx==0.28.1
COPY services/ services/
EXPOSE 8103
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8103/health')"
CMD ["uvicorn", "services.travel_api:app", "--host", "0.0.0.0", "--port", "8103"]

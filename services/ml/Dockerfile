FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "pydantic>=2.8,<3"
COPY src/ /app/src/
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "-m", "fire_risk.ml_api"]

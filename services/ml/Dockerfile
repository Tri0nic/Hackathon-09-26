FROM python:3.12-slim
WORKDIR /app
COPY services/ml/pyproject.toml /app/pyproject.toml
COPY services/ml/src/ /app/src/
RUN pip install --no-cache-dir .
COPY .artifacts/ml/catboost-synthetic-v1/ /app/model/catboost-synthetic-v1/
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "-m", "fire_risk.ml_api"]

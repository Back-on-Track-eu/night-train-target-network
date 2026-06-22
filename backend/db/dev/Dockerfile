FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir psycopg2-binary python-dotenv

COPY seed.py sql_loader.py ./
COPY sql/ ./sql/

CMD ["python", "seed.py"]

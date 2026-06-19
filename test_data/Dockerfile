FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir psycopg2-binary python-dotenv

COPY seed_database.py sql_loader.py ./
COPY sql/ ./sql/

CMD ["python", "seed_database.py"]
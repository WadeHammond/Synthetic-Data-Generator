FROM python:3.12-slim

WORKDIR /app

# pandas, pyarrow, duckdb, and psycopg2-binary all ship manylinux wheels, so no
# apt build dependencies are required.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (demo_app.py, data_layer.py, demo_ui.html, fixtures).
COPY . .

# DuckDB databases are written here at runtime; create it so the app can write
# even when the directory was excluded from the build context.
RUN mkdir -p /app/files/duckdb

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "demo_app:app", "--host", "0.0.0.0", "--port", "8000"]

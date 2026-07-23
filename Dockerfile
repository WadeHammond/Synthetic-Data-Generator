FROM python:3.12-slim

WORKDIR /app

# pandas, pyarrow, duckdb, and psycopg2-binary all ship manylinux wheels, so no
# apt build dependencies are required.
COPY requirements.txt .
# Install the CPU-only build of PyTorch first so that SDV/CTGAN reuse it instead of
# pulling the multi-GB CUDA build (Container Apps has no GPU). This keeps the image
# small and cuts the runtime memory footprint so CTGAN training fits in the container.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

# Application code (demo_app.py, data_layer.py, demo_ui.html, fixtures).
# cache-bust: bump this token to force the code layer (and everything after) to
# rebuild, so app changes always ship even when the remote build cache is warm.
ARG CODE_REV=3
RUN echo "code-rev ${CODE_REV}"
COPY . .

# DuckDB databases are written here at runtime; create it so the app can write
# even when the directory was excluded from the build context.
RUN mkdir -p /app/files/duckdb

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "demo_app:app", "--host", "0.0.0.0", "--port", "8000"]

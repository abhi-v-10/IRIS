# IRIS needs the Tesseract OCR engine, which is a native program and not a Python
# package - that is why this image exists instead of a plain Python buildpack.
FROM python:3.13-slim

# tesseract-ocr        the OCR engine that pytesseract calls
# tesseract-ocr-eng    the English language data
# libglib2.0-0, libgomp1  shared libraries that opencv-python-headless and numpy load
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the requirements first so Docker can cache the (slow) dependency layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Database, uploads and secret key live on the mounted disk, not in the image:
# a new deployment replaces the image but keeps the disk.
ENV IRIS_INSTANCE=/data \
    IRIS_HTTPS=1 \
    PYTHONUNBUFFERED=1

EXPOSE 10000

# 2 workers fit the 512 MB free tier; OCR takes ~0.5 s per receipt, so the default
# 30 s timeout is raised for multi-file uploads.
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "2", "--timeout", "120", "wsgi:app"]

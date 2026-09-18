FROM python:3.11-slim

# Instalar dependencias de sistema para OpenCV headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY . .

CMD ["python", "-u", "ws_bridge.py"]

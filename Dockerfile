# Imagen oficial de Playwright con Python y navegadores preinstalados
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Asegura navegadores de Playwright (la imagen base ya los trae; esto refuerza deps)
RUN playwright install --with-deps chromium

# Código de la aplicación
COPY app/ /app/

# Carpeta persistente de sesiones
RUN mkdir -p /app/sessions && chmod -R 777 /app/sessions

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

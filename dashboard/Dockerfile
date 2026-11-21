# Contexte de build : racine du dépôt (le dashboard réutilise queries/ et les tracés du générateur)
FROM python:3.12-slim
WORKDIR /app
COPY dashboard/requirements.txt dashboard/requirements.txt
RUN pip install --no-cache-dir -r dashboard/requirements.txt
COPY dashboard/ dashboard/
COPY queries/ queries/
COPY generator/__init__.py generator/routes.py generator/
COPY generator/data/routes_osrm.json generator/data/routes_osrm.json
EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]

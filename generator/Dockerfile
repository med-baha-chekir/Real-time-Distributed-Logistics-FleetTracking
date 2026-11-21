FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Le générateur est un package Python : il est copié dans /app/generator
COPY . ./generator/
CMD ["python", "-u", "-m", "generator.main"]

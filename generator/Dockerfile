FROM python:3.12-slim
RUN pip install --no-cache-dir pymongo
WORKDIR /app
COPY main.py .
CMD ["python","-u","main.py"]
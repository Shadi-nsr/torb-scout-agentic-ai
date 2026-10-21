FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["python", "app/server.py", "--host", "0.0.0.0", "--port", "8080"]

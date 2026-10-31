FROM python:3.13-slim
RUN pip install --no-cache-dir prometheus-client==0.26.0
COPY watchdog.py .
CMD ["python", "-u", "watchdog.py"]

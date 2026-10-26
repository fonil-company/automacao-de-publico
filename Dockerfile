FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
COPY criar_publicos_ig.py interface.py interface.html ./

RUN useradd --create-home app && chown app /app
USER app

EXPOSE 8000
CMD ["python", "interface.py"]

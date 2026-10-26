FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/app/dados

WORKDIR /app
COPY criar_publicos_ig.py interface.py interface.html ./

# Os tokens cadastrados pela página ficam aqui: monte um volume nesta pasta no Easypanel
# para eles não sumirem a cada deploy.
RUN mkdir -p /app/dados
VOLUME /app/dados

EXPOSE 8000
CMD ["python", "interface.py"]

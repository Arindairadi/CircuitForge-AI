FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ngspice kicad kicad-symbols && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
ENV PYTHONPATH=/srv DATABASE_URL=sqlite:////data/circuitforge.db
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

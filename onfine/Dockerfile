FROM python:3.12-alpine

WORKDIR /app
COPY requirements.txt .

# системные зависимости
RUN apk add --no-cache \
        build-base \
        postgresql-dev \
        gcc \
        musl-dev \
    && pip install --no-cache --upgrade pip setuptools wheel \
    && pip install --no-cache -r requirements.txt


COPY . .


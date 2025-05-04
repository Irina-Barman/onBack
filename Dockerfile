#FROM python:3.12-alpine
#
#ENV PYTHONDONTWRITEBYTECODE=1
#ENV PYTHONUNBUFFERED=1
#ENV PIP_NO_BUILD_ISOLATION=1
#
#WORKDIR /app
#COPY onfine/requirements.txt .
#RUN pip install --upgrade pip
#
#
#RUN apk add --no-cache build-base postgresql-dev gcc musl-dev \
# && pip install --no-cache -r requirements.txt
#
#
#
#
#COPY . .
# syntax=docker/dockerfile:1

FROM python:3.12-alpine

# don’t write .pyc files, unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# allow pip install to see already‐installed packages during build
#ENV PIP_NO_BUILD_ISOLATION=1

WORKDIR /app

# copy only requirements to leverage Docker cache
COPY onfine/requirements.txt .

# upgrade pip, install system deps and Python packages:
# 1) install six and kafka-python first so kafka/vendor/six.py gets populated
# 2) copy six.py into kafka/vendor manually
# 3) install the rest of your requirements
RUN pip install --upgrade pip \
 && apk add --no-cache \
      build-base \
      postgresql-dev \
      gcc \
      musl-dev \
      libffi-dev \
      openssl-dev \
 && pip install --no-cache six==1.16.0 kafka-python==2.0.0 \
 && mkdir -p /usr/local/lib/python3.12/site-packages/kafka/vendor \
 && cp /usr/local/lib/python3.12/site-packages/six.py \
       /usr/local/lib/python3.12/site-packages/kafka/vendor/six.py \
 && pip install --no-cache -r requirements.txt

# copy application code
COPY . .


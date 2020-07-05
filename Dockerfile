FROM python:3.8

ADD . .

RUN pip install --no-cache-dir -e .

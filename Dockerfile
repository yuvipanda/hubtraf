FROM python:3.6

ADD . .

RUN pip install --no-cache-dir -e .

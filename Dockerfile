FROM python:3.12
WORKDIR /opt/anxiousbot
ADD anxiousbot ./anxiousbot
ADD config ./config
ADD poetry.lock .
ADD poetry.toml .
ADD pyproject.toml .
ADD README.md .
RUN mkdir data
RUN pip install poetry
RUN poetry install
CMD poetry run main

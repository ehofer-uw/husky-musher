FROM ghcr.io/uwit-iam/uw-saml-poetry:latest AS postgresql-base

RUN apt-get update && \
    apt-get -y install git libpq-dev gcc && \
    pip install psycopg2 && \
    apt-get -y remove libpq-dev gcc

FROM postgresql-base AS app-di
WORKDIR /build
COPY poetry.lock pyproject.toml ./
RUN poetry install --no-root --no-interaction --no-dev && \
    apt-get -y remove git


FROM app-di as app
WORKDIR /app
COPY logging.yaml ./
COPY husky_musher ./husky_musher
ENTRYPOINT ["gunicorn", "husky_musher.app:create_app"]

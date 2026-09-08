#!/bin/sh

export FLASK_APP="collectives:create_app"
# Extras must be repeated on every `uv run`: it syncs the environment to the
# requested set, and would uninstall the ones it is not given.
uv run --no-dev --extra s3 flask db upgrade
uv run --no-dev --extra deploy --extra s3 waitress-serve --listen=0.0.0.0:5000 --call collectives:create_app $WAITRESS_OPTS
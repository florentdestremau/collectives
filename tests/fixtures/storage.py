"""Fixtures switching the application between the storage backends.

Tests that depend on the ``backend`` fixture are run once per backend, which is
how the test suite checks that the application behaves the same way whether
files are kept on disk or in an object store.
"""

import pytest

from collectives.utils.storage import FilesystemBackend, S3Backend

# pylint: disable=redefined-outer-name

S3_CONFIG = {
    "S3_BUCKET": "collectives-test",
    "S3_PUBLIC_URL": "https://cdn.collectives.test",
    "S3_KEY_PREFIX": "instance1/",
    "S3_URL_EXPIRATION": 600,
}
"""Configuration of the S3 backend used by the tests

:type: dict
"""


@pytest.fixture
def filesystem_backend(app, tmp_path):
    """Make the application store its files in a temporary directory.

    :returns: the backend in use
    """
    app.config["UPLOADS_DEFAULT_DEST"] = str(tmp_path)
    for key in [key for key in app.config if key.startswith("UPLOADED_")]:
        app.config[key] = str(tmp_path / key.lower())

    backend = FilesystemBackend()
    app.extensions["storage"] = backend
    return backend


@pytest.fixture
def s3_backend(app, fake_s3_client):
    """Make the application store its files in an in-memory object store.

    :returns: the backend in use
    """
    backend = S3Backend(S3_CONFIG, client=fake_s3_client)
    app.extensions["storage"] = backend
    return backend


@pytest.fixture(params=["filesystem", "s3"])
def backend(request):
    """Run the test once per storage backend.

    :returns: the backend in use
    """
    return request.getfixturevalue(f"{request.param}_backend")

"""File storage abstraction layer.

Application code stores and reads files through a
:py:class:`collectives.utils.storage.store.FileStore`, never through the file
system directly. Which backend a store uses is decided at startup by the
``STORAGE_BACKEND`` configuration key:

- ``filesystem`` (default) writes below the ``UPLOADED_<STORE>_DEST``
  directories and serves the files itself;
- ``s3`` stores the files in an S3-compatible bucket.

Typical usage::

    from collectives.utils.storage import FileStore, IMAGES

    avatars = FileStore("avatars", extensions=IMAGES, versioned=True)

    key = avatars.save(uploaded_file, name="user-42.")
    url = avatars.url(key)
    avatars.delete(key)
"""

from collectives.utils.storage.base import StorageBackend, StorageError
from collectives.utils.storage.filesystem import FilesystemBackend
from collectives.utils.storage.filesystem import blueprint as storage_blueprint
from collectives.utils.storage.s3 import S3Backend
from collectives.utils.storage.store import (
    DOCUMENTS,
    IMAGES,
    TEXT,
    FileStore,
    UploadNotAllowed,
)

BACKENDS = {
    FilesystemBackend.name: FilesystemBackend,
    S3Backend.name: S3Backend,
}
"""Available backends, by the name used in the ``STORAGE_BACKEND`` config key

:type: dict
"""


def create_backend(config) -> StorageBackend:
    """Build the storage backend described by a configuration.

    :param config: the application configuration
    :return: the backend instance
    :raises StorageError: if ``STORAGE_BACKEND`` names an unknown backend
    """
    name = config.get("STORAGE_BACKEND", FilesystemBackend.name)
    if name not in BACKENDS:
        raise StorageError(
            f"Unknown storage backend {name}, expected one of {sorted(BACKENDS)}"
        )
    backend_class = BACKENDS[name]
    if backend_class is FilesystemBackend:
        return backend_class()
    return backend_class(config)


def init_app(app):
    """Set up the storage layer of an application.

    Builds the backend from the configuration, makes it available as
    ``app.extensions["storage"]``, and registers the route serving the files if
    the backend needs the application to serve them.

    :param app: the flask application
    """
    backend = create_backend(app.config)
    app.extensions["storage"] = backend

    if backend.serves_files and storage_blueprint.name not in app.blueprints:
        app.register_blueprint(storage_blueprint)

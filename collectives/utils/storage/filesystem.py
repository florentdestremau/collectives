"""Storage backend keeping files on the local file system.

This backend reproduces the behaviour the application had when it relied on
``flask-uploads``: files are written below the ``UPLOADED_<STORE>_DEST``
directory of their store, and they are served by the application itself.
"""

import os
import shutil
from typing import IO

from flask import Blueprint, current_app, send_from_directory, url_for
from werkzeug.security import safe_join

from collectives.utils.storage.base import StorageBackend, StorageError

blueprint = Blueprint("storage", __name__, url_prefix="/storage")
"""Blueprint serving the files of the filesystem backend.

It replaces the ``_uploads`` blueprint of ``flask-uploads``. It is registered
only when the filesystem backend is in use, since an object store serves its
own files.
"""


@blueprint.route("/<store>/<path:key>")
def serve(store: str, key: str):
    """Serve a stored file.

    :param store: name of the store the file belongs to
    :param key: key of the file inside the store
    :return: the file content
    """
    backend = current_app.extensions["storage"]
    root = backend.root(store)
    if root is None:
        return "", 404
    return send_from_directory(root, key)


class FilesystemBackend(StorageBackend):
    """Stores files in a directory of the local file system.

    This is the default backend, and the one used by the test suite. It expects
    one ``UPLOADED_<STORE NAME>_DEST`` configuration key per store, as
    ``flask-uploads`` did.
    """

    name = "filesystem"
    """Name selecting this backend in the ``STORAGE_BACKEND`` configuration key

    :type: string
    """

    serves_files = True
    """Whether the application must register a route to serve the files

    :type: bool
    """

    def root(self, store) -> str:
        """Get the directory in which the files of a store are written.

        The directory is read from the ``UPLOADED_<STORE NAME>_DEST``
        configuration key. Stores that do not define one fall back to a
        subdirectory of ``UPLOADS_DEFAULT_DEST``, if it is set.

        :param store: the store, or its name
        :return: the absolute path of the store directory, or None if the store
            is unknown
        """
        name = store if isinstance(store, str) else store.name
        root = current_app.config.get(f"UPLOADED_{name.upper()}_DEST")
        if root is None:
            default = current_app.config.get("UPLOADS_DEFAULT_DEST")
            root = os.path.join(default, name) if default else None
        return root

    def path(self, store, key: str) -> str:
        """Get the absolute path of a stored file.

        :param store: the store the file belongs to
        :param key: key of the file
        :return: the absolute on-disk path
        :raises StorageError: if the store has no destination directory
        :raises ValueError: if the key tries to escape the store directory
        """
        root = self.root(store)
        if not root:
            raise StorageError(
                f"No destination configured for store {store.name}: "
                f"set UPLOADED_{store.name.upper()}_DEST or UPLOADS_DEFAULT_DEST"
            )

        path = safe_join(root, key)
        if path is None:
            raise ValueError(f"Invalid storage key {key}")
        return path

    def save(self, store, key: str, stream: IO[bytes]) -> str:
        """Write a file to disk. See :py:meth:`StorageBackend.save`."""
        if not store.overwrite and self.exists(store, key):
            key = self.resolve_conflict(store, key)

        path = self.path(store, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as destination:
            shutil.copyfileobj(stream, destination)
        return key

    def delete(self, store, key: str):
        """Remove a file from disk. See :py:meth:`StorageBackend.delete`."""
        try:
            os.remove(self.path(store, key))
        except (FileNotFoundError, OSError):
            # If the file does not exist, we just ignore the error
            pass

    def open(self, store, key: str) -> IO[bytes]:
        """Open a file from disk. See :py:meth:`StorageBackend.open`."""
        return open(self.path(store, key), "rb")

    def exists(self, store, key: str) -> bool:
        """:return: whether the file exists on disk"""
        return os.path.isfile(self.path(store, key))

    def size(self, store, key: str) -> int:
        """:return: the size of the file on disk, in bytes"""
        try:
            return os.stat(self.path(store, key)).st_size
        except (FileNotFoundError, OSError):
            return 0

    def url(self, store, key: str, external: bool = True) -> str:
        """:return: the URL of the route serving this file"""
        return url_for("storage.serve", store=store.name, key=key, _external=external)

    def image_source(self, store, key: str) -> str:
        """:return: the key itself, which ``Flask-Images`` resolves against ``IMAGES_PATH``"""
        return key

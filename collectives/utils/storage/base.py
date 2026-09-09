"""Abstract interface for the file storage backends.

The application never touches the file system directly: every write, read,
deletion and URL generation goes through a :py:class:`StorageBackend`
implementation, selected at startup from the ``STORAGE_BACKEND`` configuration
key. Two implementations are provided:

- :py:class:`collectives.utils.storage.filesystem.FilesystemBackend`, which
  reproduces the historical ``flask-uploads`` behaviour;
- :py:class:`collectives.utils.storage.s3.S3Backend`, which stores objects in
  any S3-compatible object store (AWS S3, OVH, Scaleway, MinIO, R2...).

Backends are stateless with respect to the stores: a single backend instance
serves every :py:class:`collectives.utils.storage.store.FileStore` of the
application, and each operation receives the store it applies to.
"""

import os
import posixpath
from abc import ABC, abstractmethod
from typing import IO


class StorageError(Exception):
    """Raised when a storage backend fails to complete an operation."""


class StorageBackend(ABC):
    """Interface that every storage backend must implement.

    Keys identify a file inside a store. They are relative, POSIX-style paths
    (``<folder>/<basename>``, or simply ``<basename>``), and they are persisted
    as-is in the database: a backend must never rewrite a key it is given, and
    :py:meth:`save` must return the key that was actually used so that the
    caller can store it.
    """

    @abstractmethod
    def save(self, store: "FileStore", key: str, stream: IO[bytes]) -> str:
        """Store the content of ``stream`` under ``key``.

        :param store: the store the file belongs to
        :param key: the desired key
        :param stream: the binary content to store, positioned at its start
        :return: the key actually used, which may differ from ``key`` if a file
            already existed and the store does not allow overwriting
        """

    @abstractmethod
    def delete(self, store: "FileStore", key: str):
        """Delete the file stored under ``key``.

        Deleting a missing file is not an error: the operation is idempotent.

        :param store: the store the file belongs to
        :param key: key of the file to delete
        """

    @abstractmethod
    def open(self, store: "FileStore", key: str) -> IO[bytes]:
        """Open a file for reading.

        The returned stream is seekable, so that it may be handed over to
        libraries such as PIL.

        :param store: the store the file belongs to
        :param key: key of the file to read
        :return: a seekable binary stream
        :raises FileNotFoundError: if the file does not exist
        """

    @abstractmethod
    def exists(self, store: "FileStore", key: str) -> bool:
        """:return: whether a file is stored under ``key``"""

    @abstractmethod
    def size(self, store: "FileStore", key: str) -> int:
        """:return: the size of the stored file, in bytes, or 0 if it is missing"""

    @abstractmethod
    def url(self, store: "FileStore", key: str, external: bool = True) -> str:
        """Build the URL at which a stored file can be downloaded.

        :param store: the store the file belongs to
        :param key: key of the file
        :param external: whether the URL must be absolute
        :return: the download URL
        """

    @abstractmethod
    def image_source(self, store: "FileStore", key: str) -> str:
        """Build the ``filename`` to hand over to ``Flask-Images``.

        ``Flask-Images`` resizes either a file found on disk relative to
        ``IMAGES_PATH``, or a remote file given by its absolute URL. Backends
        return whichever of the two they can offer.

        :param store: the store the file belongs to
        :param key: key of the file
        :return: a local path or an absolute URL
        """

    def resolve_conflict(self, store: "FileStore", key: str) -> str:
        """Build a free key when ``key`` is already taken.

        Mirrors the historical ``flask-uploads`` behaviour: a ``_1``, ``_2``...
        suffix is appended to the file name until a free key is found.

        :param store: the store the file belongs to
        :param key: the key that is already taken
        :return: a key that is free at the time of the call
        """
        folder, basename = posixpath.split(key)
        name, ext = os.path.splitext(basename)
        count = 0
        while True:
            count += 1
            candidate = posixpath.join(folder, f"{name}_{count}{ext}")
            if not self.exists(store, candidate):
                return candidate

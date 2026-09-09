"""Declaration of the file stores of the application.

A :py:class:`FileStore` is the object the application code talks to: it names a
family of files (avatars, event photos, documents...), knows which extensions
it accepts, and delegates every operation to the backend configured for the
current application. It plays the role ``flask_uploads.UploadSet`` used to
play, and exposes the ``file_allowed`` method the ``FileAllowed`` validator of
``Flask-WTF`` expects, so that forms need not be changed.
"""

import os
import posixpath
from secrets import token_hex
from typing import IO

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

TEXT = ("txt",)
"""Plain text extensions

:type: tuple(string)
"""

DOCUMENTS = tuple("rtf odf ods gnumeric abw doc docx xls xlsx pdf".split())
"""Office document extensions

:type: tuple(string)
"""

IMAGES = tuple("jpg jpe jpeg png gif svg bmp webp".split())
"""Image extensions displayable by most browsers

:type: tuple(string)
"""


class UploadNotAllowed(Exception):
    """Raised when trying to store a file whose extension is not allowed."""


class FileStore:
    """A named family of files, stored through the configured backend.

    :param name: the store name. It must be alphanumeric, as it appears both in
        configuration keys (``UPLOADED_<NAME>_DEST``) and in object keys.
    :param extensions: the extensions this store accepts
    :param private: whether the files must not be publicly readable. Private
        files are served through short-lived signed URLs when the backend
        supports it.
    :param overwrite: whether saving over an existing key replaces it. When
        False, a suffix is added to the file name to keep both files.
    :param versioned: whether a random token is inserted in the file name of
        every saved file. This is what allows browsers and CDNs to cache the
        files of a store forever: a new upload gets a new key, hence a new URL.
    """

    def __init__(
        self,
        name: str,
        extensions=(),
        private: bool = False,
        overwrite: bool = False,
        versioned: bool = False,
    ):
        """Constructor. See class documentation."""
        if not name.isalnum():
            raise ValueError("Store name must be alphanumeric")
        self.name = name
        self.extensions = tuple(extensions)
        self.private = private
        self.overwrite = overwrite
        self.versioned = versioned

    @property
    def backend(self):
        """The storage backend of the current application.

        :type: :py:class:`collectives.utils.storage.base.StorageBackend`
        """
        return current_app.extensions["storage"]

    # Validation, kept API-compatible with ``flask_uploads.UploadSet``

    def extension_allowed(self, ext: str) -> bool:
        """:return: whether this store accepts files with the ``ext`` extension"""
        return ext.lower().lstrip(".") in self.extensions

    def file_allowed(self, storage: FileStorage, basename: str) -> bool:
        """Check that a file may be stored.

        This is the method the ``FileAllowed`` validator of ``Flask-WTF``
        calls.

        :param storage: the uploaded file
        :param basename: the name it would be stored under
        :return: whether the file is allowed
        """
        return self.extension_allowed(os.path.splitext(basename)[1])

    # File operations

    def save(self, file: FileStorage, name: str = None, folder: str = None) -> str:
        """Store an uploaded file.

        :param file: the uploaded file
        :param name: the name to store the file under. A name ending with a dot
            gets the extension of the uploaded file appended. Defaults to the
            sanitized name of the uploaded file.
        :param folder: an optional subfolder of the store
        :return: the key under which the file has been stored
        :raises UploadNotAllowed: if the extension is not accepted by the store
        """
        if not isinstance(file, FileStorage):
            raise TypeError("file must be a werkzeug.FileStorage")

        basename = self.basename(file.filename, name)
        if not self.extension_allowed(os.path.splitext(basename)[1]):
            raise UploadNotAllowed()

        key = posixpath.join(folder, basename) if folder else basename
        file.stream.seek(0)
        return self.backend.save(self, key, file.stream)

    def basename(self, filename: str, name: str = None) -> str:
        """Build the sanitized file name a file is stored under.

        :param filename: name of the uploaded file
        :param name: requested name, see :py:meth:`save`
        :return: the file name, without any folder
        """
        ext = os.path.splitext(secure_filename(filename or ""))[1].lower()
        if name is None:
            basename = secure_filename(filename)
            basename = os.path.splitext(basename)[0] + ext
        elif name.endswith("."):
            basename = name[:-1] + ext
        else:
            basename = name

        if self.versioned:
            stem, ext = os.path.splitext(basename)
            basename = f"{stem}-{token_hex(4)}{ext}"
        return secure_filename(basename)

    def delete(self, key: str):
        """Delete a stored file, ignoring a missing one.

        :param key: key of the file, as returned by :py:meth:`save`
        """
        if key:
            self.backend.delete(self, key)

    def open(self, key: str) -> IO[bytes]:
        """Open a stored file for reading.

        :param key: key of the file
        :return: a seekable binary stream
        :raises FileNotFoundError: if the file does not exist
        """
        return self.backend.open(self, key)

    def exists(self, key: str) -> bool:
        """:return: whether a file is stored under this key"""
        return bool(key) and self.backend.exists(self, key)

    def size(self, key: str) -> int:
        """:return: the size of the stored file, in bytes, or 0 if it is missing"""
        return self.backend.size(self, key) if key else 0

    def url(self, key: str, external: bool = True) -> str:
        """:return: the URL the stored file may be downloaded from"""
        return self.backend.url(self, key, external=external)

    def image_source(self, key: str) -> str:
        """:return: the ``filename`` to pass to ``Flask-Images`` to resize this file"""
        return self.backend.image_source(self, key)

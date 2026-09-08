"""Unit tests of the file storage abstraction layer.

The same contract is checked against both backends, so that switching
``STORAGE_BACKEND`` cannot silently change the behaviour of the application.
"""

from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from collectives.utils.storage import DOCUMENTS, IMAGES, FileStore, UploadNotAllowed

# pylint: disable=redefined-outer-name


def uploaded_file(
    filename: str = "photo.png", content: bytes = b"12345"
) -> FileStorage:
    """Build an uploaded file, as a form would provide it.

    :param filename: name of the file being uploaded
    :param content: content of the file
    :return: the uploaded file
    """
    return FileStorage(stream=BytesIO(content), filename=filename)


@pytest.fixture
def store():
    """:returns: a public store accepting images and documents"""
    return FileStore("teststore", extensions=IMAGES + DOCUMENTS)


def test_save_read_and_delete(backend, store):
    """Test the life cycle of a file, on every backend."""
    key = store.save(uploaded_file("Rapport final.pdf", b"hello"))

    assert key == "Rapport_final.pdf"
    assert store.exists(key)
    assert store.size(key) == 5
    assert store.open(key).read() == b"hello"

    store.delete(key)
    assert not store.exists(key)
    assert store.size(key) == 0


def test_delete_missing_file_is_silent(backend, store):
    """Test that deleting an unknown file does not raise, on every backend."""
    store.delete("does-not-exist.pdf")


def test_open_missing_file_raises(backend, store):
    """Test that reading an unknown file raises, on every backend."""
    with pytest.raises(FileNotFoundError):
        store.open("does-not-exist.pdf")


def test_explicit_name(backend, store):
    """Test that a name ending with a dot gets the uploaded extension."""
    key = store.save(uploaded_file("IMG_2345.PNG"), name="event-12.")
    assert key == "event-12.png"


def test_refuses_unallowed_extension(backend, store):
    """Test that a file whose extension is not allowed is refused."""
    with pytest.raises(UploadNotAllowed):
        store.save(uploaded_file("payload.exe"))


def test_keeps_both_files_on_conflict(backend, store):
    """Test that saving twice under the same name keeps both files."""
    first = store.save(uploaded_file("doc.pdf", b"one"), name="doc.pdf")
    second = store.save(uploaded_file("doc.pdf", b"two"), name="doc.pdf")

    assert first != second
    assert store.open(first).read() == b"one"
    assert store.open(second).read() == b"two"


def test_overwriting_store(backend):
    """Test that an overwriting store replaces the existing file."""
    store = FileStore("overwritten", extensions=DOCUMENTS, overwrite=True)

    first = store.save(uploaded_file("doc.pdf", b"one"), name="doc.pdf")
    second = store.save(uploaded_file("doc.pdf", b"two"), name="doc.pdf")

    assert first == second
    assert store.open(second).read() == b"two"


def test_versioned_store_changes_key(backend):
    """Test that a versioned store gives a new key to every upload.

    This is what allows a new avatar to be displayed right away, instead of the
    cached previous one.
    """
    store = FileStore("versioned", extensions=IMAGES, versioned=True)

    first = store.save(uploaded_file("avatar.png"), name="user-1.")
    second = store.save(uploaded_file("avatar.png"), name="user-1.")

    assert first != second
    assert first.startswith("user-1-")
    assert first.endswith(".png")


def test_subfolder(backend, store):
    """Test that a file may be saved into a subfolder of the store."""
    key = store.save(uploaded_file("cgv.pdf"), folder="legal/v2")

    assert key == "legal/v2/cgv.pdf"
    assert store.exists(key)


def test_filesystem_url(filesystem_backend, store):
    """Test that the filesystem backend serves files from its own route."""
    key = store.save(uploaded_file("doc.pdf"))

    assert store.url(key) == f"http://localhost/storage/teststore/{key}"
    assert store.image_source(key) == key


def test_filesystem_rejects_key_escaping_the_store(filesystem_backend, store):
    """Test that a key trying to escape the store directory is rejected."""
    with pytest.raises(ValueError):
        store.exists("../../etc/passwd")


def test_s3_object_layout(s3_backend, fake_s3_client, store):
    """Test that objects are laid out as ``<prefix><store>/<key>``."""
    store.save(uploaded_file("doc.pdf", b"hello"))

    assert ("collectives-test", "instance1/teststore/doc.pdf") in fake_s3_client.objects


def test_s3_public_url(s3_backend, store):
    """Test that public files are served by the object store itself."""
    key = store.save(uploaded_file("doc.pdf"))

    expected = "https://cdn.collectives.test/instance1/teststore/doc.pdf"
    assert store.url(key) == expected
    assert store.image_source(key) == expected


def test_s3_private_files_are_signed(s3_backend):
    """Test that files of a private store are served through signed URLs."""
    store = FileStore("privatestore", extensions=DOCUMENTS, private=True)
    key = store.save(uploaded_file("secret.pdf"))

    url = store.url(key)
    assert "signature=fake" in url
    assert "expires=600" in url


def test_s3_errors_are_not_mistaken_for_missing_files(s3_backend, store, monkeypatch):
    """Test that an object store failure is not read as an absent file.

    Reporting an outage as a missing file would let the application overwrite
    or forget existing data.
    """

    def failing_head(**_kwargs):
        """Simulate an object store that is unreachable."""
        raise ConnectionError("object store is down")

    monkeypatch.setattr(s3_backend.client, "head_object", failing_head)

    with pytest.raises(ConnectionError):
        store.exists("doc.pdf")

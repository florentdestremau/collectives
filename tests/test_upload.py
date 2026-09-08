"""Tests of the file upload API, run against every storage backend.

They check that uploading, listing, downloading and deleting a file behave
identically whether the application stores its files on disk or in an object
store.
"""

import json
from io import BytesIO

from PIL import Image
from werkzeug.datastructures import FileStorage

from collectives.models import UploadedFile, db
from collectives.models.event.misc import photos
from collectives.models.upload import documents
from collectives.models.user.misc import avatars


def png_content(size=(20, 10)) -> bytes:
    """Build the content of a valid PNG image.

    :param size: dimensions of the image
    :return: the encoded image
    """
    out = BytesIO()
    Image.new("RGB", size, "#123456").save(out, "PNG")
    return out.getvalue()


def upload(client, event_id: int, filename: str, content: bytes):
    """Upload a file to an event through the API.

    :param client: the test client
    :param event_id: the event to attach the file to
    :param filename: name of the uploaded file
    :param content: content of the uploaded file
    :return: the response of the API
    """
    return client.post(
        f"/api/upload/event/{event_id}",
        data={"image": (BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def test_upload_image(backend, leader_client, event1):
    """Test uploading an image, on every storage backend."""
    content = png_content()
    response = upload(leader_client, event1.id, "Sommet.png", content)
    assert response.status_code == 200

    file = UploadedFile.query.one()
    assert file.name == "Sommet.png"
    assert file.size == len(content)
    assert file.is_image()
    assert documents.open(file.path).read() == content

    # The response points at the resizing route rather than at the raw file
    file_path = json.loads(response.data)["data"]["filePath"]
    assert "/imgsizer/" in file_path


def test_upload_document(backend, leader_client, event1):
    """Test uploading a non-image document, on every storage backend."""
    response = upload(leader_client, event1.id, "Topo.pdf", b"%PDF-1.4 topo")
    assert response.status_code == 200

    file = UploadedFile.query.one()
    assert not file.is_image()
    assert file.thumbnail_url() is None
    assert file.url().endswith(file.path)


def test_upload_refuses_unallowed_extension(backend, leader_client, event1):
    """Test that an executable cannot be uploaded, on every storage backend."""
    response = upload(leader_client, event1.id, "payload.exe", b"MZ")
    assert response.status_code == 415
    assert UploadedFile.query.count() == 0


def test_delete_uploaded_file(backend, leader_client, event1):
    """Test deleting an uploaded file, on every storage backend."""
    upload(leader_client, event1.id, "Topo.pdf", b"%PDF-1.4 topo")
    file = UploadedFile.query.one()
    key = file.path

    response = leader_client.post(f"/api/upload/delete/{file.id}")

    assert response.status_code == 200
    assert UploadedFile.query.count() == 0
    assert not documents.exists(key)


def test_is_image_is_not_recomputed(backend, leader_client, event1):
    """Test that checking a file is an image does not read it back.

    The answer is computed once at upload time: displaying a list of files must
    not download every one of them from the storage.
    """
    upload(leader_client, event1.id, "Sommet.png", png_content())

    file = UploadedFile.query.one()
    documents.delete(file.path)

    # The file is gone from the storage, yet its nature is still known
    assert file.is_image()


def test_is_image_of_legacy_file_is_computed_once(backend, leader_client, event1):
    """Test that a file uploaded before the ``is_image`` column is checked once."""
    upload(leader_client, event1.id, "Sommet.png", png_content())

    file = UploadedFile.query.one()
    file._is_image = None
    db.session.commit()

    assert file.is_image()
    assert file._is_image


def test_avatar_life_cycle(backend, user1):
    """Test saving, replacing and deleting an avatar, on every backend."""
    assert user1.save_avatar(FileStorage(BytesIO(png_content()), "avatar.png"))

    first = user1.avatar
    assert first.startswith("user-")
    assert avatars.exists(first)
    assert user1.avatar_source()

    # Uploading a new avatar gives it a new key, and drops the previous file
    assert user1.save_avatar(FileStorage(BytesIO(png_content((30, 30))), "avatar.png"))
    assert user1.avatar != first
    assert not avatars.exists(first)

    user1.delete_avatar()
    assert user1.avatar is None
    assert user1.avatar_source() is None


def test_avatar_refuses_non_image(backend, user1):
    """Test that a file that is not an image is not saved as an avatar."""
    assert not user1.save_avatar(FileStorage(BytesIO(b"not an image"), "avatar.png"))
    assert user1.avatar is None


def test_event_photo_life_cycle(backend, event1):
    """Test saving and deleting an event photo, on every backend."""
    assert event1.save_photo(FileStorage(BytesIO(png_content()), "photo.png"))

    key = event1.photo
    assert photos.exists(key)
    assert event1.photo_source()

    event1.delete_photo()
    assert event1.photo is None
    assert not photos.exists(key)

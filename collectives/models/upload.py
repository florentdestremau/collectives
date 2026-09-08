"""Module for file upload related classes"""

import os
from datetime import timedelta

from flask import url_for
from sqlalchemy.orm import validates
from werkzeug.utils import secure_filename

from collectives.models.globals import db
from collectives.models.user import User
from collectives.utils.misc import is_valid_image
from collectives.utils.storage import DOCUMENTS, IMAGES, FileStore
from collectives.utils.time import current_time

documents = FileStore("documents", extensions=DOCUMENTS + IMAGES + ("gpx",))
"""Store for the files attached to events and activities

:type: :py:class:`collectives.utils.storage.FileStore`
"""


THUMBNAIL_WIDTH = 640
"""Default width in pixels for image thumbnails """

THUMBNAIL_HEIGHT = 480
"""Default height in pixels for image thumbnails """


class UploadedFile(db.Model):
    """User-uploaded file.

    For now, each uploaded file is linked to an event. This may change in the future
    """

    __tablename__ = "uploaded_files"

    id = db.Column(db.Integer, primary_key=True)
    """Upload unique id.

    :type: int
    """

    name = db.Column(db.String(255), nullable=False)
    """Original file name

    :type: string
    """

    path = db.Column(db.Text(), nullable=False)
    """On-disk path

    :type: string
    """

    date = db.Column(db.DateTime, nullable=False)
    """Upload date

    :type: :py:class:`datetime.datetime`
    """

    size = db.Column(db.Integer, nullable=False)
    """Size, in bytes

    :type: Integer
    """

    _is_image = db.Column("is_image", db.Boolean, nullable=True)
    """Whether the file is a valid image, computed once when it is uploaded.

    Null for files uploaded before this column existed; see
    :py:meth:`is_image`.

    :type: bool
    """

    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), index=True)
    """ Primary key of the event to which this file belong

    :type: int
    """

    activity_id = db.Column(db.Integer, db.ForeignKey("activity_types.id"), index=True)
    """ Primary key of the activity to which this file belong

    :type: int
    """

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    """ Primary key of the user who uploaded this file

    :type: int
    """

    session_id = db.Column(db.String(36), nullable=True)
    """If the upload is not associated to an event yet, id of the edit session

    :type: string
    """

    # Relationships
    event = db.relationship(
        "Event",
        backref=db.backref("uploaded_files", cascade="all, delete-orphan"),
        lazy=True,
    )
    """ Event to which this file belongs. May be null

    :type: :py:class:`collectives.models.event.Event`
    """

    activity = db.relationship(
        "ActivityType",
        backref=db.backref("uploaded_files", cascade="all, delete-orphan"),
        lazy=True,
    )
    """ Activity to which this file belong. May be null

    :type: :py:class:`collectives.models.event.Event`
    """

    user = db.relationship(
        "User",
        backref=db.backref("uploaded_files", cascade="all, delete-orphan"),
        lazy=True,
    )
    """ User who uploaded this file

    :type: :py:class:`collectives.models.user.User`
    """

    @validates("name")
    def validate_filename(self, key, value):
        """Makes a file name secure and truncates it to the max SQL field length
        :param string key: name of field to validate
        :param string value: tentative value
        :return: Truncated file name.
        :rtype: string
        """
        if not value:
            return value

        max_len = getattr(self.__class__, key).prop.columns[0].type.length
        value = secure_filename(value)
        if len(value) > max_len:
            name, ext = os.path.splitext(value)
            max_name_length = max_len - 1 - len(ext)
            return name[:max_name_length] + ext
        return value

    def is_image(self):
        """Checks if this file is an image

        The answer is computed once when the file is uploaded and stored in
        database, as reading the file back is expensive when it does not live
        on a local disk. Files uploaded before that column existed are checked
        on first access, then remembered.

        :return: True if the file is a valid image
        :rtype: bool
        """
        if self._is_image is None:
            self._is_image = self.check_is_image()
        return self._is_image

    def check_is_image(self, file=None):
        """Reads the file to check whether it is a valid image.

        :param file: the uploaded file, if it is still at hand. Otherwise the
            stored file is read back.
        :type file: :py:class:`werkzeug.datastructures.FileStorage`
        :return: True if the extension is an image extension and the content is
            a valid image
        :rtype: bool
        """
        ext = os.path.splitext(self.name)[1][1:].lower()
        if ext not in IMAGES:
            return False

        try:
            stream = file.stream if file is not None else documents.open(self.path)
            return is_valid_image(stream)
        except (FileNotFoundError, OSError):
            return False

    def save_file(self, file):
        """Save from a raw file

        :param file: The direct output of a FileInput
        :type file: :py:class:`werkzeug.datastructures.FileStorage`
        """
        self.name = file.filename
        name, ext = os.path.splitext(self.name)
        self._is_image = self.check_is_image(file)
        self.path = documents.save(
            file, name=f"{self.date.strftime('%y_%m_%d')}_{name}{ext}"
        )
        self.size = documents.size(self.path)

    def delete_file(self):
        """Deletes the stored file"""
        documents.delete(self.path)
        self.path = None
        self.size = 0

    def url(self):
        """:returns: the URL an uploaded file can be downloaded from
        :rtype: str
        """
        return documents.url(self.path)

    def thumbnail_url(
        self, width: int = THUMBNAIL_WIDTH, height: int = THUMBNAIL_HEIGHT
    ):
        """
        If this file is an image, returns its thumbnail URL

        :param width: max width of the thumbnail in pixels, defaults to THUMBNAIL_WIDTH
        :type width: int, optional
        :param height: max height of the thumnail in pixels, defaults to THUMBNAIL_HEIGHT
        :type height: int, optional
        :return: The thumbnail URL or None if not an image
        :rtype: int
        """
        return (
            url_for(
                "images.fit",
                filename=documents.image_source(self.path),
                width=width,
                height=height,
                _external=True,
            )
            if self.is_image()
            else None
        )

    @staticmethod
    def purge_old_uploads(current_session_id: int, days: int = 1):
        """Removes uploaded files from temporary sessions that where never attached to an event

        :param current_session_id: Id of current editing session, or None. Files from the current
            editing session will not be purged.
        :type current_session_id: int
        :param days: Number of days since upload to consider purging the file
        :type days: int
        """
        to_delete = UploadedFile.query.filter(UploadedFile.event_id.is_(None))
        to_delete = to_delete.filter(UploadedFile.activity_id.is_(None))
        to_delete = to_delete.filter(UploadedFile.session_id != current_session_id)
        to_delete = to_delete.filter(
            UploadedFile.date <= current_time() - timedelta(days=days)
        )
        for file_to_delete in to_delete.all():
            file_to_delete.delete_file()
            db.session.delete(file_to_delete)

    def has_edit_rights(self, user: User):
        """Checks whether an user has edit rights on this file

         - if the file is associated to an activity, user needs to be a supervisor
         - if the file is associated to an event, user needs edit rights on event
         - if the file is unassociated, user needs to have uploaded it

        :param user: user to check
        :type user: :py:class:`collectives.models.User`
        :return: whether the user has edit rights
        :rtype: bool
        """
        if user.is_moderator():
            return True

        if self.activity_id is not None:
            return user.supervises_activity(self.activity_id)
        if self.event_id is not None:
            return self.event.has_edit_rights(user)
        return self.user_id == user.id

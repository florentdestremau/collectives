"""Storage backend keeping files in an S3-compatible object store.

Only the ``boto3`` client API is used, and the endpoint is configurable, so
this backend works with Amazon S3 as well as with any compatible provider
(OVH Object Storage, Scaleway, MinIO, Cloudflare R2...).

Objects are laid out as ``<S3_KEY_PREFIX><store name>/<key>``, which mirrors
the directory layout of the filesystem backend: an existing installation may
therefore be migrated with a plain ``aws s3 sync`` of the upload directories,
without touching the paths already recorded in the database.
"""

from io import BytesIO
from typing import IO

from collectives.utils.storage.base import StorageBackend, StorageError

NOT_FOUND_CODES = ("404", "NoSuchKey", "NoSuchBucket", "NotFound")
"""Error codes an S3 client uses to report a missing object

:type: tuple(string)
"""


def is_missing(error: Exception) -> bool:
    """Tell whether an error raised by the client means the object is missing.

    Any other error (network failure, wrong credentials, missing right) must
    not be mistaken for an absent file, or the application would happily
    overwrite or forget existing data.

    :param error: the error raised by the client
    :return: whether the object does not exist
    """
    response = getattr(error, "response", None) or {}
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in NOT_FOUND_CODES or status == 404


class S3Backend(StorageBackend):
    """Stores files as objects in an S3 bucket.

    Public files are served directly by the object store (or by a CDN in front
    of it) through :py:attr:`public_url`; files of a private store are served
    through short-lived pre-signed URLs.

    :param config: application configuration, read once at startup
    :param client: ``boto3`` S3 client to use. If ``None``, a client is built
        lazily from the configuration. Mostly useful for tests.
    """

    name = "s3"
    """Name selecting this backend in the ``STORAGE_BACKEND`` configuration key

    :type: string
    """

    serves_files = False
    """Whether the application must register a route to serve the files

    :type: bool
    """

    def __init__(self, config, client=None):
        """Constructor. See class documentation."""
        self.bucket = config["S3_BUCKET"]
        self.endpoint_url = config.get("S3_ENDPOINT_URL")
        self.region = config.get("S3_REGION")
        self.access_key = config.get("S3_ACCESS_KEY_ID")
        self.secret_key = config.get("S3_SECRET_ACCESS_KEY")
        self.prefix = config.get("S3_KEY_PREFIX") or ""
        self.expiration = config.get("S3_URL_EXPIRATION", 3600)
        self.public_url = (config.get("S3_PUBLIC_URL") or "").rstrip("/")
        self._client = client

    @property
    def client(self):
        """The ``boto3`` S3 client, built on first use.

        ``boto3`` is an optional dependency: it is imported here so that an
        installation using the filesystem backend does not need it.

        :type: :py:class:`botocore.client.BaseClient`
        """
        if self._client is None:
            try:
                # pylint: disable=import-outside-toplevel
                import boto3
            except ImportError as err:
                raise StorageError(
                    "boto3 is required by the S3 storage backend. "
                    "Install the 's3' extra of the project."
                ) from err

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
            )
        return self._client

    def object_key(self, store, key: str) -> str:
        """Build the full object key of a stored file.

        :param store: the store the file belongs to
        :param key: key of the file inside the store
        :return: the object key inside the bucket
        """
        return f"{self.prefix}{store.name}/{key}"

    def save(self, store, key: str, stream: IO[bytes]) -> str:
        """Upload a file to the bucket. See :py:meth:`StorageBackend.save`."""
        if not store.overwrite and self.exists(store, key):
            key = self.resolve_conflict(store, key)

        self.client.upload_fileobj(stream, self.bucket, self.object_key(store, key))
        return key

    def delete(self, store, key: str):
        """Delete an object. See :py:meth:`StorageBackend.delete`.

        ``delete_object`` succeeds on a missing object, so nothing special is
        needed to make the operation idempotent.
        """
        self.client.delete_object(Bucket=self.bucket, Key=self.object_key(store, key))

    def open(self, store, key: str) -> IO[bytes]:
        """Download an object in memory. See :py:meth:`StorageBackend.open`.

        The whole object is buffered because callers (PIL, in particular) need
        a seekable stream. Uploads being capped by ``MAX_CONTENT_LENGTH``, this
        stays bounded.
        """
        buffer = BytesIO()
        try:
            self.client.download_fileobj(
                self.bucket, self.object_key(store, key), buffer
            )
        except Exception as err:
            if is_missing(err):
                raise FileNotFoundError(key) from err
            raise
        buffer.seek(0)
        return buffer

    def exists(self, store, key: str) -> bool:
        """:return: whether an object is stored under this key"""
        return self.head(store, key) is not None

    def size(self, store, key: str) -> int:
        """:return: the size of the object, in bytes, or 0 if it is missing"""
        head = self.head(store, key)
        return 0 if head is None else head.get("ContentLength", 0)

    def head(self, store, key: str):
        """Fetch the metadata of an object.

        :param store: the store the file belongs to
        :param key: key of the file
        :return: the ``head_object`` response, or None if the object is missing
        :raises Exception: any error that is not a missing object is propagated
        """
        try:
            return self.client.head_object(
                Bucket=self.bucket, Key=self.object_key(store, key)
            )
        except Exception as err:
            if is_missing(err):
                return None
            raise

    def url(self, store, key: str, external: bool = True) -> str:
        """Build the download URL of an object.

        Files of a private store get a pre-signed URL, valid for
        ``S3_URL_EXPIRATION`` seconds. Other files are served directly by the
        object store or its CDN.

        :param store: the store the file belongs to
        :param key: key of the file
        :param external: unused, object store URLs are always absolute
        :return: the download URL
        """
        object_key = self.object_key(store, key)
        if store.private:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=self.expiration,
            )
        if not self.public_url:
            raise StorageError("S3_PUBLIC_URL is required to serve public files")
        return f"{self.public_url}/{object_key}"

    def image_source(self, store, key: str) -> str:
        """Build the URL ``Flask-Images`` downloads the image from.

        .. warning::
            ``Flask-Images`` caches remote images under the hash of their URL:
            a private store, whose URLs are signed and thus change on every
            call, would defeat that cache and must not be resized.

        :param store: the store the file belongs to
        :param key: key of the file
        :return: the absolute URL of the image
        """
        return self.url(store, key)

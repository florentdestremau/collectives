"""In-memory replacement for the ``boto3`` S3 client.

It implements the handful of operations
:py:class:`collectives.utils.storage.s3.S3Backend` uses, so that the S3 backend
can be exercised by the test suite without a network access nor a bucket.
"""

import pytest


class FakeS3Error(Exception):
    """Raised by :py:class:`FakeS3Client` when an object does not exist.

    Stands for the ``botocore.exceptions.ClientError`` the real client raises,
    and carries the same ``response`` attribute.
    """

    def __init__(self, key: str):
        """Constructor.

        :param key: key of the missing object
        """
        super().__init__(key)
        self.response = {
            "Error": {"Code": "404", "Message": "Not Found"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }


class FakeS3Client:
    """Minimal in-memory S3 client.

    Objects are kept in the :py:attr:`objects` dictionary, keyed by
    ``(bucket, key)``, which tests may inspect directly.
    """

    def __init__(self):
        """Constructor. Starts with an empty bucket."""
        self.objects = {}

    def upload_fileobj(self, stream, bucket: str, key: str, ExtraArgs=None):
        """Store the content of a stream as an object.

        :param stream: the binary content to store
        :param bucket: name of the bucket
        :param key: object key
        :param ExtraArgs: unused, kept for signature compatibility with boto3
        """
        # pylint: disable=invalid-name
        self.objects[(bucket, key)] = stream.read()

    def download_fileobj(self, Bucket: str, Key: str, Fileobj):
        """Write the content of an object into a stream.

        :param Bucket: name of the bucket
        :param Key: object key
        :param Fileobj: the stream to write to
        :raises FakeS3Error: if the object does not exist
        """
        # pylint: disable=invalid-name
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error(Key)
        Fileobj.write(self.objects[(Bucket, Key)])

    def head_object(self, Bucket: str, Key: str):
        """Return the metadata of an object.

        :param Bucket: name of the bucket
        :param Key: object key
        :return: a dict holding the object size
        :raises FakeS3Error: if the object does not exist
        """
        # pylint: disable=invalid-name
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error(Key)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket: str, Key: str):
        """Delete an object, ignoring a missing one.

        :param Bucket: name of the bucket
        :param Key: object key
        """
        # pylint: disable=invalid-name
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, operation: str, Params: dict, ExpiresIn: int):
        """Build a fake signed URL.

        :param operation: the operation to sign, eg ``get_object``
        :param Params: the operation parameters, holding the bucket and key
        :param ExpiresIn: lifetime of the URL, in seconds
        :return: a URL carrying a fake signature
        """
        # pylint: disable=invalid-name
        return (
            f"https://fake-s3.test/{Params['Bucket']}/{Params['Key']}"
            f"?operation={operation}&expires={ExpiresIn}&signature=fake"
        )


@pytest.fixture
def fake_s3_client():
    """:returns: a fresh :py:class:`FakeS3Client`"""
    return FakeS3Client()

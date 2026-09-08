File storage
=============

User uploaded files (event photos, avatars, documents attached to events...)
are never read or written directly by the application code: they go through
the :py:mod:`collectives.utils.storage` layer, which hides where the files
actually live.

Two backends are available, selected by the ``STORAGE_BACKEND`` configuration
key:

- ``filesystem`` (default) writes the files in the ``UPLOADED_*_DEST``
  directories and serves them from the ``/storage`` route of the application;
- ``s3`` stores them in an S3-compatible bucket (Amazon S3, but also OVH
  Object Storage, Scaleway, MinIO or Cloudflare R2, as the endpoint is
  configurable).

Stores
-------

A store is a named family of files. It knows the extensions it accepts, whether
its files are public, and how their names are built::

    from collectives.utils.storage import FileStore, IMAGES

    avatars = FileStore("avatars", extensions=IMAGES, versioned=True)

    key = avatars.save(uploaded_file, name="user-42.")
    url = avatars.url(key)
    avatars.delete(key)

The key returned by ``save`` is what must be stored in database. It is a
relative path, identical for both backends, which is what makes moving from one
to the other possible without touching the data.

A ``versioned`` store adds a random token to every file name. This is what
allows a new avatar to show up immediately: the file gets a new key, hence a
new URL, that no browser nor CDN has cached yet.

Using an object store
----------------------

.. warning::
    Files of public stores are readable by anyone knowing their URL, exactly as
    they are today when served by the application. Private stores (used for
    the confidential configuration files) must **not** be made public: they are
    served through short-lived signed URLs.

Configuration, either in ``instance/config.py`` or through environment
variables:

.. code-block:: python

    STORAGE_BACKEND = "s3"
    S3_BUCKET = "collectives-uploads"
    S3_ENDPOINT_URL = "https://s3.gra.io.cloud.ovh.net"  # empty for Amazon S3
    S3_REGION = "gra"
    S3_ACCESS_KEY_ID = "..."
    S3_SECRET_ACCESS_KEY = "..."
    S3_PUBLIC_URL = "https://collectives-uploads.s3.gra.io.cloud.ovh.net"
    S3_KEY_PREFIX = ""  # eg "test/" to share a bucket between instances

The ``boto3`` dependency is optional; install it with the ``s3`` extra::

    uv sync --extra s3

Migrating an existing installation
------------------------------------

Objects are laid out as ``<S3_KEY_PREFIX><store name>/<key>``, which mirrors
the layout of the upload directories. Migrating therefore only requires copying
the files, the paths recorded in database staying valid::

    aws s3 sync collectives/static/uploads/documents s3://collectives-uploads/documents/
    aws s3 sync collectives/static/uploads/avatars   s3://collectives-uploads/avatars/

Once the files are copied and ``STORAGE_BACKEND`` is set to ``s3``, the
persistent volume is only needed for the stores that have not been migrated
yet.

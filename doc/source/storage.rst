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

.. warning::
    ``uv run`` syncs the environment to the extras it is given, and uninstalls
    the others: every ``uv run`` of a deployment must repeat ``--extra s3``, as
    ``deployment/docker/entrypoint.sh`` does. The docker image ships ``boto3``
    (about 30 MB) whichever backend is in use.

Bucket and credentials
------------------------

Two policies are needed. The first one is for the account whose keys the
application uses. ``head_object``, used to read a file size and check for a
conflicting name, is covered by ``s3:GetObject``:

.. code-block:: json

    {"Version": "2012-10-17", "Statement": [
      {"Effect": "Allow",
       "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
       "Resource": "arn:aws:s3:::collectives-uploads/*"},
      {"Effect": "Allow", "Action": ["s3:ListBucket"],
       "Resource": "arn:aws:s3:::collectives-uploads"}
    ]}

The second one lets browsers read the files, and is restricted to the prefixes
that are actually served:

.. code-block:: json

    {"Version": "2012-10-17", "Statement": [
      {"Sid": "PublicRead", "Effect": "Allow", "Principal": "*",
       "Action": "s3:GetObject",
       "Resource": ["arn:aws:s3:::collectives-uploads/avatars/*",
                    "arn:aws:s3:::collectives-uploads/photos/*",
                    "arn:aws:s3:::collectives-uploads/documents/*"]}
    ]}

On Amazon S3, the bucket *Block Public Access* setting must be turned off for
this policy to take effect. Other providers expose the same thing as a public
container or the very same bucket policy.

.. note::
    This makes the event attachments readable by anyone knowing their URL. That
    is already the case today, as they are served without authentication, so
    this is not a regression — but it is the right moment to decide whether it
    should stay that way. If not, the ``documents`` store must be declared
    ``private``, and its files will then be served through signed URLs.

No CORS configuration is needed: images are loaded through ``<img>`` tags, not
by scripts.

Migrating an existing installation
------------------------------------

Objects are laid out as ``<S3_KEY_PREFIX><store name>/<key>``, which mirrors
the layout of the upload directories, so migrating only requires copying the
files: the paths recorded in database stay valid.

.. warning::
    Event photos live at the **root** of the upload directory
    (``UPLOADED_PHOTOS_DEST`` is ``static/uploads`` itself), next to the
    subdirectories of the other stores. Copying them requires excluding
    everything that sits in a subdirectory, or the whole volume ends up
    duplicated under ``photos/``.

.. code-block:: bash

    E="--endpoint-url https://s3.gra.io.cloud.ovh.net"  # omit for Amazon S3
    B=s3://collectives-uploads

    aws $E s3 sync collectives/static/uploads/documents $B/documents/
    aws $E s3 sync collectives/static/uploads/avatars   $B/avatars/
    aws $E s3 sync collectives/static/uploads           $B/photos/ --exclude "*/*"

Kubernetes runbook
....................

The persistent volume claim is ``ReadWriteOnce``, so a job cannot mount it
while the application pod holds it. The deployment already uses the
``Recreate`` strategy, meaning a short interruption is part of every release
anyway: the simplest path is a ten minute maintenance window.

#. Build and publish the image, and create the bucket, the account and the two
   policies above. Check the credentials from a workstation before going
   further.

#. Add the credentials to the existing secret:

   .. code-block:: yaml

       stringData:
         s3_access_key_id: --to-be-replaced--
         s3_secret_access_key: --to-be-replaced--

#. Optionally, pre-copy the files while the site is still up, with
   ``kubectl cp`` and the commands above. Files are only ever added, never
   modified, so the delta left to copy during the window becomes negligible.

#. Open the window: ``kubectl scale deploy/collectives --replicas=0``.

#. Copy the files with ``kubectl apply -f deployment/k8s/migrate-uploads-to-s3.yaml``,
   and wait for the job to complete.

#. Set ``STORAGE_BACKEND`` and the ``S3_*`` variables in the deployment (the
   block is present, commented out, in ``collectives.example.yaml``), apply,
   and scale back to one replica. The entrypoint runs ``flask db upgrade``,
   which adds the ``is_image`` column.

#. Check, in that order: the home page (event photos), an avatar, then a full
   round trip — attach a file to a test event, check the object appears in the
   bucket, delete it, check it is gone.

Rolling back
..............

Remove ``STORAGE_BACKEND`` from the deployment and apply again. The volume is
untouched and the ``is_image`` column is nullable, so an older image tolerates
it. Only the files uploaded while running on the object store are missing from
the volume; a reversed ``aws s3 sync`` brings them back. Keep the volume for a
few weeks before deleting it.

What still needs the volume
.............................

Only three of the six stores are migrated. ``imgtypeequip``, ``tech`` and
``private`` — which hold, among others, the club logo, the terms of sale and
the volunteer certificate template — are still written to disk. Until they are
migrated too, the volume must stay mounted, the ``Recreate`` strategy must stay,
and the deployment cannot be scaled beyond one replica.

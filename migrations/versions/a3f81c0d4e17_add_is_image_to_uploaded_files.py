"""add is_image to uploaded_files

Revision ID: a3f81c0d4e17
Revises: dfadf58f0fac
Create Date: 2026-09-08 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f81c0d4e17'
down_revision = 'dfadf58f0fac'
branch_labels = None
depends_on = None


def upgrade():
    # Cache whether an uploaded file is a valid image, so that displaying a
    # file list does not require reading every file back from the storage.
    with op.batch_alter_table('uploaded_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_image', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('uploaded_files', schema=None) as batch_op:
        batch_op.drop_column('is_image')

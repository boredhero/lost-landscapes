"""Add morphology families without changing existing detection records."""
from alembic import op

revision = "b004"
down_revision = "b003"


def upgrade():
    # SQLAlchemy persists enum member NAMES, not lowercase API values.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'MOUND'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'PLATFORM'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'LINEAR_BANK'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'LINEAR_DITCH'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'ENCLOSURE'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'REPEATED_PATTERN'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'RIDGE'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'HOLLOW'")
        op.execute("ALTER TYPE featuretype ADD VALUE IF NOT EXISTS 'SCARP'")


def downgrade():
    # PostgreSQL cannot safely remove enum values while detections reference them.
    pass

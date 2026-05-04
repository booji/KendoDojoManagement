"""add_federations_table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-04 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "federations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("abbreviation", sa.String(50), nullable=True),
        sa.Column("iso_code", sa.String(10), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("continental_grouping", sa.String(100), nullable=True),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )

    # Seed the 67 FIK affiliate federations
    import uuid

    seed_data = [
        # Global (1)
        {
            "name": "International Kendo Federation",
            "abbreviation": "FIK",
            "continental_grouping": "Global",
            "type": "Global Body",
            "website": "https://www.kendo-fik.org",
        },
        # Regional (2)
        {
            "name": "European Kendo Federation",
            "abbreviation": "EKF",
            "continental_grouping": "Europe",
            "type": "Regional Body",
            "website": "https://www.ekf-kendo.eu",
        },
        {
            "name": "Latin American Kendo Confederation",
            "abbreviation": "LAKC",
            "continental_grouping": "Pan-Am",
            "type": "Regional Body",
        },
        # Africa (12)
        {"name": "Botswana Kendo Federation", "abbreviation": "BKF", "iso_code": "BW", "continental_grouping": "Africa", "type": "National"},
        {"name": "Congo Kendo Federation", "abbreviation": "CKF", "iso_code": "CG", "continental_grouping": "Africa", "type": "National"},
        {"name": "Ghana Kendo Association", "abbreviation": "GKA", "iso_code": "GH", "continental_grouping": "Africa", "type": "National"},
        {"name": "Ivory Coast Kendo Federation", "abbreviation": "FCKCI", "iso_code": "CI", "continental_grouping": "Africa", "type": "National"},
        {"name": "Kenya Kendo Association", "abbreviation": "KKA", "iso_code": "KE", "continental_grouping": "Africa", "type": "National"},
        {"name": "Madagascar Kendo Association", "abbreviation": "MKA", "iso_code": "MG", "continental_grouping": "Africa", "type": "National"},
        {"name": "Morocco Kendo Federation", "abbreviation": "FMK", "iso_code": "MA", "continental_grouping": "Africa", "type": "National"},
        {"name": "Nigeria Kendo Association", "abbreviation": "NKA", "iso_code": "NG", "continental_grouping": "Africa", "type": "National"},
        {"name": "Reunion Kendo Federation", "abbreviation": "RKF", "iso_code": "RE", "continental_grouping": "Africa", "type": "National"},
        {"name": "Senegal Kendo Federation", "abbreviation": "FKS", "iso_code": "SN", "continental_grouping": "Africa", "type": "National"},
        {"name": "South Africa Kendo Federation", "abbreviation": "SAKF", "iso_code": "ZA", "continental_grouping": "Africa", "type": "National"},
        {"name": "Tunisia Kendo Federation", "abbreviation": "FTK", "iso_code": "TN", "continental_grouping": "Africa", "type": "National"},
        # Asia (26)
        {"name": "All India Kendo Federation", "abbreviation": "AIKF", "iso_code": "IN", "continental_grouping": "Asia", "type": "National"},
        {"name": "All Nepal Kendo Federation", "abbreviation": "ANKF", "iso_code": "NP", "continental_grouping": "Asia", "type": "National"},
        {"name": "Bangladesh Kendo Association", "abbreviation": "BKA", "iso_code": "BD", "continental_grouping": "Asia", "type": "National"},
        {"name": "Chinese Taipei Kendo Federation", "abbreviation": "CTKF", "iso_code": "TW", "continental_grouping": "Asia", "type": "National"},
        {"name": "Chinese Kendo Federation", "abbreviation": "CKF-CN", "iso_code": "CN", "continental_grouping": "Asia", "type": "National"},
        {"name": "Hong Kong Kendo Association", "abbreviation": "HKKA", "iso_code": "HK", "continental_grouping": "Asia", "type": "National"},
        {"name": "Indonesia Kendo Association", "abbreviation": "IKA", "iso_code": "ID", "continental_grouping": "Asia", "type": "National"},
        {"name": "Iranian Kendo Federation", "abbreviation": "IKF", "iso_code": "IR", "continental_grouping": "Asia", "type": "National"},
        {"name": "Iraq Kendo Federation", "abbreviation": "IrKF", "iso_code": "IQ", "continental_grouping": "Asia", "type": "National"},
        {"name": "Israel Kendo Association", "abbreviation": "IKA-IL", "iso_code": "IL", "continental_grouping": "Europe/Asia", "type": "National"},
        {"name": "Japan Kendo Federation", "abbreviation": "AJKF", "iso_code": "JP", "continental_grouping": "Asia", "type": "National"},
        {"name": "Jordan Kendo Federation", "abbreviation": "JKF-JO", "iso_code": "JO", "continental_grouping": "Asia", "type": "National"},
        {"name": "Kazakhstan Kendo Federation", "abbreviation": "KKF", "iso_code": "KZ", "continental_grouping": "Asia", "type": "National"},
        {"name": "Korea Kendo Association", "abbreviation": "KKA-KR", "iso_code": "KR", "continental_grouping": "Asia", "type": "National"},
        {"name": "Kuwait Kendo Federation", "abbreviation": "KuKF", "iso_code": "KW", "continental_grouping": "Asia", "type": "National"},
        {"name": "Macao Kendo Federation", "abbreviation": "MKF", "iso_code": "MO", "continental_grouping": "Asia", "type": "Special Status"},
        {"name": "Malaysia Kendo Association", "abbreviation": "MKA-MY", "iso_code": "MY", "continental_grouping": "Asia", "type": "National"},
        {"name": "Mongolia Kendo Federation", "abbreviation": "MoKF", "iso_code": "MN", "continental_grouping": "Asia", "type": "National"},
        {"name": "Myanmar Kendo Association", "abbreviation": "MKA-MM", "iso_code": "MM", "continental_grouping": "Asia", "type": "National"},
        {"name": "Pakistan Kendo Federation", "abbreviation": "PKF", "iso_code": "PK", "continental_grouping": "Asia", "type": "National"},
        {"name": "Philippines Kendo Federation", "abbreviation": "PKF-PH", "iso_code": "PH", "continental_grouping": "Asia", "type": "National"},
        {"name": "Singapore Kendo Federation", "abbreviation": "SKF", "iso_code": "SG", "continental_grouping": "Asia", "type": "National"},
        {"name": "Sri Lanka Kendo Federation", "abbreviation": "SLKF", "iso_code": "LK", "continental_grouping": "Asia", "type": "National"},
        {"name": "Thailand Kendo Association", "abbreviation": "TKA", "iso_code": "TH", "continental_grouping": "Asia", "type": "National"},
        {"name": "Turkey Kendo Federation", "abbreviation": "TKF", "iso_code": "TR", "continental_grouping": "Europe/Asia", "type": "National"},
        {"name": "United Arab Emirates Kendo Federation", "abbreviation": "UAEKF", "iso_code": "AE", "continental_grouping": "Asia", "type": "National"},
        {"name": "Vietnam Kendo Federation", "abbreviation": "VKF", "iso_code": "VN", "continental_grouping": "Asia", "type": "National"},
        # Oceania (2)
        {"name": "Australia Kendo Renmei", "abbreviation": "AKR", "iso_code": "AU", "continental_grouping": "Oceania", "type": "National"},
        {"name": "New Zealand Kendo Federation", "abbreviation": "NZKF", "iso_code": "NZ", "continental_grouping": "Oceania", "type": "National"},
        # Pan-Am (16)
        {"name": "Aruba Kendo Federation", "abbreviation": "AKF-AW", "iso_code": "AW", "continental_grouping": "Pan-Am", "type": "Special Status"},
        {"name": "Argentine Kendo Federation", "abbreviation": "FAK", "iso_code": "AR", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Brazilian Kendo Confederation", "abbreviation": "CBK", "iso_code": "BR", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Canada Kendo Federation", "abbreviation": "CKF-CA", "iso_code": "CA", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Chile Kendo Federation", "abbreviation": "FKC", "iso_code": "CL", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Colombia Kendo Federation", "abbreviation": "FKCo", "iso_code": "CO", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Costa Rica Kendo Federation", "abbreviation": "CRKF", "iso_code": "CR", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Dominican Republic Kendo Association", "abbreviation": "DRKA", "iso_code": "DO", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Ecuador Kendo Federation", "abbreviation": "EKF-EC", "iso_code": "EC", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Guatemala Kendo Federation", "abbreviation": "GKF", "iso_code": "GT", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Mexico Kendo Federation", "abbreviation": "FMK-MX", "iso_code": "MX", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Panama Kendo Federation", "abbreviation": "PANKF", "iso_code": "PA", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Peru Kendo Federation", "abbreviation": "PKF-PE", "iso_code": "PE", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "United States Kendo Federation", "abbreviation": "USKF", "iso_code": "US", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Uruguay Kendo Federation", "abbreviation": "UKF", "iso_code": "UY", "continental_grouping": "Pan-Am", "type": "National"},
        {"name": "Venezuela Kendo Federation", "abbreviation": "VenKF", "iso_code": "VE", "continental_grouping": "Pan-Am", "type": "National"},
        # Europe (8)
        {"name": "Austrian Kendo Federation", "abbreviation": "AKF-AT", "iso_code": "AT", "continental_grouping": "Europe", "type": "National"},
        {"name": "Belgian Kendo Federation", "abbreviation": "BKF-BE", "iso_code": "BE", "continental_grouping": "Europe", "type": "National"},
        {"name": "British Kendo Association", "abbreviation": "BKA", "iso_code": "GB", "continental_grouping": "Europe", "type": "National", "website": "https://www.britishkendo.co.uk"},
        {"name": "Czech Kendo Federation", "abbreviation": "CKF-CZ", "iso_code": "CZ", "continental_grouping": "Europe", "type": "National"},
        {"name": "French Kendo Federation", "abbreviation": "FFKDA", "iso_code": "FR", "continental_grouping": "Europe", "type": "National"},
        {"name": "German Kendo Federation", "abbreviation": "DKenV", "iso_code": "DE", "continental_grouping": "Europe", "type": "National"},
        {"name": "Irish Kendo Association", "abbreviation": "IKA-IE", "iso_code": "IE", "continental_grouping": "Europe", "type": "National"},
        {"name": "Italian Kendo Federation", "abbreviation": "FIKS", "iso_code": "IT", "continental_grouping": "Europe", "type": "National"},
    ]

    rows = []
    for entry in seed_data:
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "name": entry["name"],
                "abbreviation": entry.get("abbreviation"),
                "iso_code": entry.get("iso_code"),
                "website": entry.get("website"),
                "continental_grouping": entry.get("continental_grouping"),
                "type": entry.get("type"),
                "is_pinned": False,
                "is_active": True,
            }
        )

    op.bulk_insert(
        sa.table(
            "federations",
            sa.column("id", sa.String),
            sa.column("name", sa.String),
            sa.column("abbreviation", sa.String),
            sa.column("iso_code", sa.String),
            sa.column("website", sa.String),
            sa.column("continental_grouping", sa.String),
            sa.column("type", sa.String),
            sa.column("is_pinned", sa.Boolean),
            sa.column("is_active", sa.Boolean),
        ),
        rows,
    )


def downgrade() -> None:
    op.drop_table("federations")

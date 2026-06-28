"""
seed_admin.py
=============
Seed data and seeder for the admin schema.

Tables covered:
  admin.users
  admin.auth_tokens  (empty — tokens are runtime-only, never seeded)
  admin.feedback     (empty — no seed data needed)
"""

# ============================================================
# Seed data
# ============================================================

USERS = [
    {
        "email":        "david@backontrack.eu",
        "display_name": "david",
        "is_verified":  True,
    },
    {
        "email":        "bjarne@backontrack.eu",
        "display_name": "bjarne",
        "is_verified":  True,
    },
]


# ============================================================
# Seeder
# ============================================================

def seed_admin(cur, insert_rows) -> int:
    """
    Seed the admin schema. Returns the user_id of the first seeded user
    (used as demo_user_id by the proposals seeder).
    """
    print("Seeding admin.users...")
    insert_rows(cur, "admin.users", USERS)

    cur.execute("SELECT user_id FROM admin.users ORDER BY user_id LIMIT 1")
    demo_user_id = cur.fetchone()[0]
    return demo_user_id
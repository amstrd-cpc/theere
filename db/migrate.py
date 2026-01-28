from __future__ import annotations

from db.migrations import migrate

if __name__ == "__main__":
    migrate()
    print("✅ Database migrations complete")

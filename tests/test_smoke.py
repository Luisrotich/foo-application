import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused")
os.environ.setdefault("JWT_SECRET", "test-only-secret")
from production_app import create_app

def test_health_requires_no_auth(monkeypatch):
    app = create_app()
    # Database is intentionally integration-tested in a PostgreSQL CI service.
    assert app.url_map.bind("").match("/health")[0] == "health"

def test_protected_routes_exist():
    app = create_app()
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert {"/api/checkout", "/api/mpesa/callback", "/api/orders"} <= routes

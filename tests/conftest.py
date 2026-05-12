"""Fixtures pytest para Solplast ERP."""
import os
import sys

# Permite import de modulos del proyecto desde tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Desactiva Supabase real para tests
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["SRI_SIMULADO"] = "true"
os.environ["APP_PASSWORD"] = ""
os.environ["APP_PASSWORD_OP"] = ""
os.environ["FLASK_ENV"] = "development"

import pytest


@pytest.fixture
def app():
    from server import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()

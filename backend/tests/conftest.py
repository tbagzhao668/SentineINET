import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def main_module():
    from app import main as main_module
    return main_module


@pytest.fixture()
def client(main_module):
    main_module.app.router.on_startup.clear()
    main_module.app.router.on_shutdown.clear()
    return TestClient(main_module.app)


@pytest.fixture()
def reset_db(main_module):
    main_module.db["devices"] = {}
    main_module.db["skills"] = []
    main_module.db["inspections"] = {}
    main_module.db["health_data"] = {}
    main_module.db["last_run"] = {}
    main_module.db["pending_actions"] = []
    main_module.db["policy_history"] = {}
    main_module.db["backup_servers"] = {}
    main_module.db["agent_sessions"] = {}
    main_module.db["settings"] = {"auto_inspect": False, "enabled_devices": []}
    yield


@pytest.fixture()
def client_e2e(main_module):
    main_module.app.router.on_startup.clear()
    main_module.app.router.on_shutdown.clear()
    main_module._load_persisted_state()
    return TestClient(main_module.app)

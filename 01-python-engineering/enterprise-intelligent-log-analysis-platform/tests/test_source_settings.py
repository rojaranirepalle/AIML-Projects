from fastapi.testclient import TestClient
import pytest
from app.api import app
from app.config import log_source


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(log_source, "SOURCE_SETTINGS_PATH", tmp_path / "source.json")
    return TestClient(app)


def test_saved_source_applies_to_default_consumers(client, timestamped_log):
    result = client.put('/settings/log-source', json={'log_file_path': str(timestamped_log)})
    assert result.status_code == 200
    assert client.get('/settings/log-source').json()['log_file_path'] == str(timestamped_log)
    assert client.get('/dashboard-data').json()['total'] == 37
    assert client.get('/summary').json()['total_logs'] == 37
    assert client.post('/logs', json={}).json()['total'] == 37
    assert client.get('/explorer/records').json()['total'] == 37
    assert log_source.get_log_path() == timestamped_log


def test_invalid_source_preserves_saved_path(client, timestamped_log, tmp_path):
    client.put('/settings/log-source', json={'log_file_path': str(timestamped_log.parent)})
    for value in ['', str(tmp_path / 'missing.log')]:
        assert client.put('/settings/log-source', json={'log_file_path': value}).status_code == 400
    assert log_source.get_log_path() == timestamped_log.parent


def test_settings_page_and_navigation(client):
    assert 'Log files root directory path' in client.get('/settings').text
    for page in ['/dashboard', '/explorer']:
        assert 'href="/settings"' in client.get(page).text


def test_root_directory_rejects_file(client, timestamped_log):
    response = client.put('/settings/log-source', json={'log_file_path': str(timestamped_log), 'directory_only': True})
    assert response.status_code == 400
    assert not log_source.SOURCE_SETTINGS_PATH.exists()

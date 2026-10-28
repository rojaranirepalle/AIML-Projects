import json
import stat

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import app
from app.config import llm_settings
from app.config.settings import settings
from app.services import llm_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_settings, 'LLM_SETTINGS_PATH', tmp_path / 'llm.json')
    monkeypatch.setattr(settings, 'incident_summary_enabled', False)
    for name in ['incident_summary_api_key', 'openai_api_key', 'anthropic_api_key', 'gemini_api_key']:
        monkeypatch.setattr(settings, name, None)
    return TestClient(app)


def config(client, **updates):
    current = client.get('/settings/llm').json()
    return {**{key: current[key] for key in ['enabled', 'provider', 'openai_model', 'anthropic_model', 'gemini_model']}, **updates}


def test_secret_is_persisted_privately_and_never_returned(client):
    response = client.put('/settings/llm', json=config(client, enabled=True, openai_api_key='test-secret-only'))
    assert response.status_code == 200
    assert response.json()['openai_key_configured'] is True
    assert 'test-secret-only' not in response.text
    assert 'test-secret-only' not in client.get('/settings/llm').text
    assert stat.S_IMODE(llm_settings.LLM_SETTINGS_PATH.stat().st_mode) == 0o600
    assert llm_client._api_key('openai') == 'test-secret-only'
    assert llm_client.availability() is None
    client.put('/settings/llm', json=config(client, openai_api_key=''))
    assert llm_client._api_key('openai') == 'test-secret-only'
    assert client.put('/settings/llm', json=config(client, enabled=False)).status_code == 200
    assert 'disabled' in llm_client.availability()


@pytest.mark.parametrize('provider', ['openai', 'anthropic', 'gemini'])
def test_saved_provider_is_used_by_actual_client(client, monkeypatch, provider):
    payload = config(client, enabled=True, provider=provider, **{f'{provider}_model': 'test-model', f'{provider}_api_key': 'test-key'})
    assert client.put('/settings/llm', json=payload).status_code == 200
    assert llm_client.provider_name() == provider
    assert llm_client.model_name() == 'test-model'
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({'choices': [{'message': {'content': 'ok'}}], 'content': [{'type': 'text', 'text': 'ok'}], 'candidates': [{'content': {'parts': [{'text': 'ok'}]}}]}).encode()

    def fake_urlopen(request, timeout):
        captured['request'] = request
        return Response()

    monkeypatch.setattr(llm_client, 'urlopen', fake_urlopen)
    assert llm_client.complete('system', 'masked evidence') == 'ok'
    request = captured['request']
    assert 'test-model' in request.full_url or json.loads(request.data)['model'] == 'test-model'
    assert 'test-key' in dict(request.header_items()).values() or 'Bearer test-key' in dict(request.header_items()).values()


def test_invalid_provider_or_model_does_not_overwrite(client):
    assert client.put('/settings/llm', json=config(client, provider='invalid')).status_code == 422
    assert client.put('/settings/llm', json=config(client, openai_model='   ')).status_code == 400
    assert not llm_settings.LLM_SETTINGS_PATH.exists()


def test_environment_fallback_and_provider_key_override(client, monkeypatch):
    monkeypatch.setattr(settings, 'incident_summary_api_key', SecretStr('shared-test-key'))
    assert client.get('/settings/llm').json()['shared_key_configured']
    assert llm_client._api_key('openai') == 'shared-test-key'
    client.put('/settings/llm', json=config(client, openai_api_key='specific-test-key'))
    assert llm_client._api_key('openai') == 'specific-test-key'

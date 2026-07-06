"""Unit tests for Flask route handlers in flask-frontend/app.py.

gRPC stubs are mocked so the tests run without live bank servers.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'flask-frontend'))

from app import app


@pytest.fixture()
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret'
    with app.test_client() as c:
        yield c


def _login_admin(client):
    return client.post('/login', data={
        'login_type': 'admin',
        'username': 'admin',
        'password': 'admin',
    }, follow_redirects=False)


def _login_client_user(client, username='ana_peru_solo'):
    return client.post('/login', data={
        'login_type': 'client',
        'username': username,
        'password': '123456',
    }, follow_redirects=False)


# ── Login / logout ─────────────────────────────────────────────────────────

class TestAuth:
    def test_login_page_renders(self, client):
        resp = client.get('/')
        assert resp.status_code == 200

    def test_admin_login_redirect(self, client):
        resp = _login_admin(client)
        assert resp.status_code == 302
        assert '/dashboard' in resp.headers['Location']

    def test_admin_login_bad_password(self, client):
        resp = client.post('/login', data={
            'login_type': 'admin',
            'username': 'admin',
            'password': 'wrong',
        })
        assert resp.status_code == 200
        assert 'inválidas' in resp.data.decode()

    def test_client_login_redirect(self, client):
        resp = _login_client_user(client)
        assert resp.status_code == 302
        assert '/transfers' in resp.headers['Location']

    def test_client_login_bad_password(self, client):
        resp = client.post('/login', data={
            'login_type': 'client',
            'username': 'ana_peru_solo',
            'password': 'wrong',
        })
        assert resp.status_code == 200
        assert 'inválidas' in resp.data.decode()

    def test_logout_clears_session(self, client):
        _login_admin(client)
        resp = client.get('/logout', follow_redirects=False)
        assert resp.status_code == 302
        assert '/' in resp.headers['Location']


# ── Protected routes require auth ──────────────────────────────────────────

class TestProtectedRoutes:
    @pytest.mark.parametrize("path", [
        '/dashboard', '/accounts', '/transfers', '/history',
        '/banks', '/monitoring', '/coordination',
    ])
    def test_redirect_when_not_logged_in(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302

    def test_api_transfer_requires_auth(self, client):
        resp = client.post('/api/transfer', json={})
        assert resp.status_code == 401

    def test_api_account_operation_requires_auth(self, client):
        resp = client.post('/api/account-operation', json={})
        assert resp.status_code == 401


# ── Client-restricted routes ──────────────────────────────────────────────

class TestClientRestrictions:
    def test_client_redirected_from_dashboard(self, client):
        _login_client_user(client)
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/transfers' in resp.headers['Location']

    def test_client_redirected_from_banks(self, client):
        _login_client_user(client)
        resp = client.get('/banks', follow_redirects=False)
        assert resp.status_code == 302

    def test_client_redirected_from_coordination(self, client):
        _login_client_user(client)
        resp = client.get('/coordination', follow_redirects=False)
        assert resp.status_code == 302


# ── API: account-operation validation ─────────────────────────────────────

class TestApiAccountOperation:
    def test_invalid_operation(self, client):
        _login_admin(client)
        resp = client.post('/api/account-operation', json={
            'operation': 'invalid',
            'account_id': 'PE001',
            'amount': 100,
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'inválida' in data['message'].lower()

    def test_missing_account(self, client):
        _login_admin(client)
        resp = client.post('/api/account-operation', json={
            'operation': 'deposit',
            'account_id': '',
            'amount': 100,
        })
        assert resp.status_code == 400

    def test_non_numeric_amount(self, client):
        _login_admin(client)
        resp = client.post('/api/account-operation', json={
            'operation': 'deposit',
            'account_id': 'PE001',
            'amount': 'abc',
        })
        assert resp.status_code == 400

    def test_negative_amount(self, client):
        _login_admin(client)
        resp = client.post('/api/account-operation', json={
            'operation': 'deposit',
            'account_id': 'PE001',
            'amount': -50,
        })
        assert resp.status_code == 400

    def test_unknown_bank_from_account(self, client):
        _login_admin(client)
        resp = client.post('/api/account-operation', json={
            'operation': 'deposit',
            'account_id': 'XX001',
            'amount': 100,
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'banco' in data['message'].lower()


# ── API: transfer validation ──────────────────────────────────────────────

class TestApiTransfer:
    def test_missing_fields(self, client):
        _login_admin(client)
        resp = client.post('/api/transfer', json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert not data['success']

    def test_non_numeric_amount(self, client):
        _login_admin(client)
        resp = client.post('/api/transfer', json={
            'source_bank': 'peru',
            'dest_bank': 'chile',
            'source_account': 'PE001',
            'dest_account': 'CH001',
            'amount': 'xyz',
        })
        assert resp.status_code == 400


# ── API: force-election and events require admin ──────────────────────────

class TestAdminOnlyApis:
    def test_force_election_forbidden_for_client(self, client):
        _login_client_user(client)
        resp = client.post('/api/force-election', json={})
        assert resp.status_code == 403

    def test_events_forbidden_for_client(self, client):
        _login_client_user(client)
        resp = client.get('/api/events')
        assert resp.status_code == 403

    def test_coordination_data_forbidden_for_client(self, client):
        _login_client_user(client)
        resp = client.get('/coordination/data')
        assert resp.status_code == 403

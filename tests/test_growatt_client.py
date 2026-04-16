import pytest
from unittest.mock import patch, MagicMock
from datetime import date

def test_login_sets_session(config):
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
    assert client.logged_in
    mock_api.session.headers.update.assert_called_once()

def test_get_hourly_data(config):
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_api.dashboard_data.return_value = {
        "chartData": {
            "12:00": {"ppv": "4.6", "sysOut": "1.6", "userLoad": "3.0", "pacToUser": "0"},
            "12:05": {"ppv": "4.8", "sysOut": "1.5", "userLoad": "3.3", "pacToUser": "0"},
        },
    }
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        data = client.get_hourly_data(date(2026, 3, 26))
    assert len(data) == 2
    assert data["12:00"]["ppv"] == "4.6"
    assert data["12:00"]["sysOut"] == "1.6"
    assert data["12:00"]["userLoad"] == "3.0"

def test_set_charge_soc(config):
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"msg": "inv_set_success", "success": True}
    mock_api.session.post.return_value = mock_resp
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        result = client.set_charge_soc(75)
    assert result is True
    call_args = mock_api.session.post.call_args
    posted_data = call_args[1].get("data") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["data"]
    assert posted_data["param2"] == "75"

def test_get_current_soc(config):
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_api.device_list.return_value = [{"deviceSn": "ABC123", "capacity": "45%"}]
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        soc = client.get_current_soc()
    assert soc == 45

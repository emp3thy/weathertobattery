import pytest
from unittest.mock import patch, MagicMock
from datetime import date

def test_login_sets_session(config):
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt, rates=config.rates)
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
        client = GrowattClient(config.growatt, rates=config.rates)
        client.login()
        data = client.get_hourly_data(date(2026, 3, 26))
    assert len(data) == 2
    assert data["12:00"]["ppv"] == "4.6"
    assert data["12:00"]["sysOut"] == "1.6"
    assert data["12:00"]["userLoad"] == "3.0"

def _post_params(mock_api):
    call_args = mock_api.session.post.call_args
    return call_args[1]["data"] if "data" in call_args[1] else call_args[0][1]


def test_set_charge_soc_uses_configured_wrap_window(config):
    """Cheap window 23:30-05:30 wraps midnight: slot1=23:30-23:59, slot2=00:00-05:30."""
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"msg": "inv_set_success", "success": True}
    mock_api.session.post.return_value = mock_resp
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt, rates=config.rates)
        client.login()
        assert client.set_charge_soc(75) is True
    data = _post_params(mock_api)
    assert data["param2"] == "75"
    assert (data["param3"], data["param4"]) == ("23", "30")
    assert (data["param5"], data["param6"]) == ("23", "59")
    assert data["param7"] == "1"
    assert (data["param8"], data["param9"]) == ("00", "00")
    assert (data["param10"], data["param11"]) == ("05", "30")
    assert data["param12"] == "1"
    assert data["param17"] == "0"


def test_set_charge_soc_non_wrapping_window(tmp_path):
    """Cheap window 01:00-05:00 (no wrap): slot1 uses it, slot2 disabled."""
    from src.growatt.client import GrowattClient
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        VALID_CONFIG_YAML
        .replace('cheap_start: "23:30"', 'cheap_start: "01:00"')
        .replace('cheap_end: "05:30"', 'cheap_end: "05:00"')
    )
    cfg = load_config(cfg_path)

    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"msg": "inv_set_success", "success": True}
    mock_api.session.post.return_value = mock_resp
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(cfg.growatt, rates=cfg.rates)
        client.login()
        client.set_charge_soc(60)
    data = _post_params(mock_api)
    assert (data["param3"], data["param4"]) == ("01", "00")
    assert (data["param5"], data["param6"]) == ("05", "00")
    assert data["param7"] == "1"
    assert data["param12"] == "0"

def test_get_current_soc(config):
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_api.device_list.return_value = [{"deviceSn": config.growatt.device_sn, "capacity": "45%"}]
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt, rates=config.rates)
        client.login()
        soc = client.get_current_soc()
    assert soc == 45


def test_charge_periods_wrap_midnight(config):
    from src.growatt.client import GrowattClient
    client = GrowattClient(config.growatt, rates=config.rates)
    assert client._charge_periods() == [(23, 30, 23, 59), (0, 0, 5, 30)]


def test_charge_periods_non_wrapping(tmp_path):
    from src.growatt.client import GrowattClient
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        VALID_CONFIG_YAML
        .replace('cheap_start: "23:30"', 'cheap_start: "02:00"')
        .replace('cheap_end: "05:30"', 'cheap_end: "06:15"')
    )
    cfg = load_config(cfg_path)
    client = GrowattClient(cfg.growatt, rates=cfg.rates)
    assert client._charge_periods() == [(2, 0, 6, 15)]


def test_charge_periods_rejects_equal_start_end(tmp_path):
    import pytest
    from src.growatt.client import GrowattClient
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        VALID_CONFIG_YAML
        .replace('cheap_start: "23:30"', 'cheap_start: "03:00"')
        .replace('cheap_end: "05:30"', 'cheap_end: "03:00"')
    )
    cfg = load_config(cfg_path)
    client = GrowattClient(cfg.growatt, rates=cfg.rates)
    with pytest.raises(ValueError):
        client._charge_periods()

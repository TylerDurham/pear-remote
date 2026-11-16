import tomllib

import pytest

from peard.core.config import DEFAULT_PORT, Config, Device, config_path


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    """Point XDG_CONFIG_HOME at a temp dir so tests never touch the real config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def _load(path):
    return tomllib.loads(path.read_text())


def test_defaults():
    cfg = Config()
    assert cfg.devices == []
    assert cfg.active is None
    assert cfg.port == DEFAULT_PORT


def test_default_devices_list_not_shared():
    a, b = Config(), Config()
    a.devices.append(Device(identifier="x"))
    assert b.devices == []

def test_config_save(isolated_config_home):
    expected = Config()
    device = Device(name="First Device", identifier="First")
    expected.devices.append(device)
    device = Device(name="Second Device", identifier="Second")
    expected.devices.append(device)
    expected.save()

    actual = Config.load()
    assert actual == expected


def test_save_writes_to_config_path(isolated_config_home):
    path = Config().save()
    assert path == config_path()
    assert path == isolated_config_home / "peard-remote" / "config.toml"
    assert path.exists()




def test_save_empty_config():
    data = _load(Config().save())
    assert data == {"port": DEFAULT_PORT}


def test_save_with_active_and_devices():
    cfg = Config(
        devices=[
            Device(identifier="AA:BB", name="Living Room", host="192.168.1.10"),
            Device(identifier="CC:DD"),
        ],
        active="AA:BB",
        port=9000,
    )
    data = _load(cfg.save())
    assert data == {
        "port": 9000,
        "active": "AA:BB",
        "devices": [
            {"identifier": "AA:BB", "name": "Living Room", "host": "192.168.1.10"},
            {"identifier": "CC:DD"},
        ],
    }


def test_save_escapes_quotes_and_backslashes():
    tricky = 'Tyler\'s "Den" \\ TV'
    cfg = Config(devices=[Device(identifier="id1", name=tricky)])
    data = _load(cfg.save())
    assert data["devices"][0]["name"] == tricky

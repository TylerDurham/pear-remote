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
    print(f"Loading config from '{config_path()}")
    expected = Config()

    expected.devices.append(Device(name="First Device", identifier="AA:BB:CC:DD"))
    expected.active = expected.devices[0].identifier
    expected.devices.append(Device(name="Second Device", identifier="00:11:22:33"))
    expected.save()

    actual = Config.load()
    assert actual == expected


def test_config_find_device(isolated_config_home):

    print(f"Loading config from '{config_path()}")
    expected = Config()

    expected.devices.append(Device(name="First Device", identifier="AA:BB:CC:DD"))
    expected.active = expected.devices[0].identifier
    expected.devices.append(Device(name="Second Device", identifier="00:11:22:33"))
    expected.save()

    actual = Config.load()

    for d in actual.devices:
        t = actual.find(d.identifier)
        assert t == d


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
    cfg.save()
    data = cfg.load()
    assert data.devices[0].name == tricky


@pytest.fixture
def two_devices():
    return Config(
        devices=[
            Device(name="Living Room", identifier="AA:BB:CC:DD"),
            Device(name="Bedroom", identifier="00:11:22:33"),
        ]
    )


def test_find_by_exact_name(two_devices):
    assert two_devices.find("Bedroom") is two_devices.devices[1]


def test_find_by_case_insensitive_name_prefix(two_devices):
    assert two_devices.find("living") is two_devices.devices[0]


def test_find_ambiguous_prefix_returns_none():
    cfg = Config(
        devices=[
            Device(name="Living Room", identifier="1"),
            Device(name="Living Room 2", identifier="2"),
        ]
    )
    assert cfg.find("liv") is None


def test_find_no_match_returns_none(two_devices):
    assert two_devices.find("Kitchen") is None


def test_current_returns_active_device(two_devices):
    two_devices.active = "00:11:22:33"
    assert two_devices.current is two_devices.devices[1]


def test_current_defaults_to_first_device(two_devices):
    assert two_devices.active is None
    assert two_devices.current is two_devices.devices[0]


def test_current_unknown_active_falls_back_to_first(two_devices):
    two_devices.active = "does-not-exist"
    assert two_devices.current is two_devices.devices[0]


def test_current_with_no_devices_is_none():
    assert Config().current is None

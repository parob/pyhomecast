"""Tests for pyhomecast data models."""

from pyhomecast.models import HomecastState, _key_to_name


def test_key_to_name():
    assert _key_to_name("ceiling_light_a1b2") == "Ceiling Light"
    assert _key_to_name("my_home_0bf8") == "My Home"
    assert _key_to_name("living_room_a1b2") == "Living Room"


def test_key_to_name_no_suffix():
    assert _key_to_name("simple") == "Simple"


def test_parse_state_response_empty():
    state = HomecastState.from_api_response({"_meta": {"fetched_at": "2024-01-01"}})
    assert len(state.devices) == 0
    assert len(state.homes) == 0


def test_parse_state_response_single_home():
    raw = {
        "my_home_0bf8": {
            "living_room_a1b2": {
                "ceiling_light_c3d4": {
                    "type": "light",
                    "on": True,
                    "brightness": 80,
                    "_settable": ["on", "brightness"],
                    "name": "my_home_0bf8.living_room_a1b2.ceiling_light_c3d4",
                }
            }
        },
        "_meta": {"fetched_at": "2024-01-01T00:00:00+00:00"},
    }

    state = HomecastState.from_api_response(raw)

    assert len(state.homes) == 1
    assert "my_home_0bf8" in state.homes
    assert state.homes["my_home_0bf8"].name == "My Home"

    assert len(state.devices) == 1
    device = state.devices["my_home_0bf8.living_room_a1b2.ceiling_light_c3d4"]
    assert device.name == "Ceiling Light"
    assert device.room_name == "Living Room"
    assert device.device_type == "light"
    assert device.state["on"] is True
    assert device.state["brightness"] == 80
    assert device.settable == ["on", "brightness"]
    assert device.home_key == "my_home_0bf8"
    assert device.room_key == "living_room_a1b2"
    assert device.accessory_key == "ceiling_light_c3d4"


def test_parse_state_response_multiple_homes():
    raw = {
        "home_one_0001": {
            "room_a_aaaa": {
                "light_1111": {"type": "light", "on": True, "_settable": ["on"]}
            }
        },
        "home_two_0002": {
            "room_b_bbbb": {
                "switch_2222": {"type": "switch", "on": False, "_settable": ["on"]}
            }
        },
        "_meta": {},
    }

    state = HomecastState.from_api_response(raw)
    assert len(state.homes) == 2
    assert len(state.devices) == 2


def test_parse_state_response_group():
    raw = {
        "my_home_0bf8": {
            "living_room_a1b2": {
                "all_lights_c3d4": {
                    "type": "light",
                    "on": True,
                    "group": True,
                    "_settable": ["on"],
                    "accessories": {},
                }
            }
        },
        "_meta": {},
    }

    state = HomecastState.from_api_response(raw)
    device = state.devices["my_home_0bf8.living_room_a1b2.all_lights_c3d4"]
    assert device.is_group is True


def test_parse_state_skips_meta_keys():
    raw = {
        "_meta": {"fetched_at": "2024-01-01"},
        "my_home_0bf8": {
            "_meta": "should be skipped",
            "room_a1b2": {
                "_internal": "skip",
                "light_c3d4": {"type": "light", "on": True, "_settable": ["on"]},
            },
        },
    }

    state = HomecastState.from_api_response(raw)
    assert len(state.devices) == 1

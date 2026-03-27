# pyhomecast

Async Python client for the [Homecast](https://homecast.cloud) REST API.

## Installation

```bash
pip install pyhomecast
```

## Usage

```python
import aiohttp
from pyhomecast import HomecastClient

async with aiohttp.ClientSession() as session:
    client = HomecastClient(session)
    client.authenticate("your_access_token")

    # Get all device state
    state = await client.get_state()
    for device in state.devices.values():
        print(f"{device.name} ({device.device_type}): {device.state}")

    # Control a device
    await client.set_state({
        "my_home_0bf8": {
            "living_room_a1b2": {
                "ceiling_light_c3d4": {"on": True, "brightness": 80}
            }
        }
    })

    # Run a scene
    await client.run_scene("my_home_0bf8", "Good Morning")
```

## API

### `HomecastClient(session, api_url="https://api.homecast.cloud")`

- `authenticate(token)` - Set the Bearer token
- `get_state(home?, room?, device_type?, name?)` - Fetch device state (returns `HomecastState`)
- `set_state(updates)` - Control devices
- `run_scene(home, name)` - Execute a scene

### Models

- `HomecastState` - Contains `devices` and `homes` dicts
- `HomecastDevice` - Single device with `state`, `settable`, `device_type`
- `HomecastHome` - Home with `key` and `name`

### Exceptions

- `HomecastError` - Base exception
- `HomecastAuthError` - 401/403 errors
- `HomecastConnectionError` - Network/server errors

## License

MIT

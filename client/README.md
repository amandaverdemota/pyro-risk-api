# pyroriskclient

Tiny Python client for the [Pyronear risk API](https://github.com/MateoLostanlen/pyro-risk-api).

## Install

```bash
pip install "git+https://github.com/MateoLostanlen/pyro-risk-api.git#subdirectory=client"
```

## Usage

```python
from pyroriskclient import Client

api = Client(
    host="https://riskapi.pyronear.org",
    username="admin",
    password="...",
)

api.health()                                    # {"status": "ok"}
api.list_cameras()                              # [{"id": 1, "name": "...", "fwi": 0.0, ...}, ...]
api.get_camera(1)                               # {"id": 1, ...}
api.get_scores("2026-05-04")                    # all cameras on that day
api.get_scores("2026-05-04", camera_id=1)       # one camera on that day

api.recompute_scores("2026-04-01", "2026-04-30")  # schedule a backfill
```

All methods return parsed JSON. Errors (4xx/5xx) raise
`requests.HTTPError`.

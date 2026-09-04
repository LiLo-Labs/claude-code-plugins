# Setup

## 1. The Blender addon

Blender 3.0 or newer.

1. **Edit > Preferences > Add-ons > Install**, choose
   `plugins/blender/blendpipe/addon.py`.
2. Enable **Interface: BlendPipe Bridge**.
3. In the 3D viewport press **N**, open the **BlendPipe** tab, press **Start**.

The panel shows the port it is listening on. If you change it, set
`BLENDPIPE_PORT` to match.

The bridge only ever listens on `127.0.0.1`. It executes arbitrary Python inside
Blender by design — that is what makes procedural modelling work — so treat
starting it the same way you would treat opening a Python console: fine on your
own machine, not something to expose to a network.

## 2. A mesh backend, if you want generation

Optional. Procedural modelling through `execute_python` needs no backend at all.

| Backend | Variable | Rough cost |
|---|---|---|
| your hardware | `BLENDPIPE_LOCAL_URL` | free — see `local-backend.md` |
| Tripo | `TRIPO_API_KEY` | ~$0.15/generation |
| Meshy | `MESHY_API_KEY` | ~$0.20/generation |
| Rodin | `RODIN_API_KEY` | ~$0.40/generation |

Unset, the first configured backend in that order wins, so a local generator
takes over the moment it exists. `BLENDPIPE_BACKEND` pins one explicitly.

## 3. Other settings

| Variable | Default | What it does |
|---|---|---|
| `BLENDPIPE_PORT` | `9876` | must match the addon panel |
| `BLENDPIPE_HOST` | `127.0.0.1` | |
| `BLENDPIPE_RUNS` | `~/.blendpipe/runs` | generated meshes, renders, session state |
| `BLENDPIPE_MAX_GENERATIONS` | `10` | paid generations allowed per session |
| `BLENDPIPE_VERIFY_MAX_AGE` | `1800` | seconds a verify stays valid for export |

## 4. Check it

```
/blender-status
```

## Tests

```
python3 plugins/blender/tests/test_blendpipe.py
```

No pytest, no network, and no Blender — a fake speaks the addon's protocol so the
wiring, the gates and the guardrails are all testable on their own.

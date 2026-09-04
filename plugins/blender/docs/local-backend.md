# Running generation on your own hardware

The paid backends and this one are interchangeable. Wrap whatever open-weight
generator you want in the endpoint below, set `BLENDPIPE_LOCAL_URL`, and it takes
over automatically — `local` sits first in the preference order, so no other
setting has to change and no API key keeps quietly costing money.

## The contract

```
POST {BLENDPIPE_LOCAL_URL}/generate
     {"prompt": "a mossy stone golem", "options": {...}}
```

Reply with any one of:

```jsonc
{"path": "/abs/path/on/this/machine.glb"}   // best: no bytes move
{"url":  "http://host/result.glb"}          // fetched over HTTP
{"job":  "abc123"}                          // polled below
```

For the job form:

```
GET {BLENDPIPE_LOCAL_URL}/status/abc123
    -> {"done": false}
    -> {"done": true, "path": "..."}        // or "url"
    -> {"error": "out of memory"}           // fails the generation
```

`path` is the right answer when the GPU box shares a filesystem with Claude Code,
which is the usual case for hardware you run yourself.

There is no auth in the contract on purpose. This is meant to be bound to
localhost or a private network; a token scheme here would be security theatre.
If it must cross an untrusted network, put it behind something that does auth
properly rather than adding a header here.

## A minimal server

```python
# pip install fastapi uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import tempfile, os

app = FastAPI()
pipeline = load_your_model()          # Hunyuan3D, TRELLIS, TripoSR, ...

class Request(BaseModel):
    prompt: str
    options: dict = {}

@app.post("/generate")
def generate(request: Request):
    out = os.path.join(tempfile.mkdtemp(), "mesh.glb")
    pipeline(request.prompt, **request.options).export(out)
    return {"path": out}
```

```bash
uvicorn server:app --host 127.0.0.1 --port 8000
export BLENDPIPE_LOCAL_URL=http://127.0.0.1:8000
```

If a generation takes longer than a couple of minutes, return `{"job": id}` and
implement `/status/{id}` instead — the submit request has a 120s timeout, while
the polling path allows 30 minutes by default.

## Then what

Nothing else changes. `list_backends` will show `local  your hardware  READY`,
the spend guard stops counting generations because they are free, and the skill
stops warning about cost. The verify and render loop is identical — an
open-weight model produces exactly the same triangle soup at arbitrary scale that
a paid one does, and the gates are what make either usable.

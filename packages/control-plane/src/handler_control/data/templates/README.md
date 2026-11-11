# templates

Starting points the web UI and the CLI fill their forms from: not files to copy. What you create
from one gets the name you give it, and is written to `~/.config/handler-ai/`.

- `providers/`: one per kind of model server (`handler.provider/v1`, contract E). `apiKey = { secret =
  "key" }` only says that the server needs a key: the form asks for it, and it goes to Handler's secret
  store. The model lists are a start: edit them to what the server serves.

# Apps addon — provisioning

Nothing to provision: the addon brings the skill, and needs no account. Bun comes with the
toolbox.

1. A binding, `~/.config/handler-ai/bindings/app-builder.toml`:

   ```toml
   apiVersion = "handler.binding/v1"
   addon = "app-builder"
   ```

2. An agent on the app's folder that selects it, with a filtered network (the addon adds
   `registry.npmjs.org`, for the UI's build and the backend's type check).
3. When the agent is done: Apps page → Add (the folder) → Deploy. Only you deploy
   (docs/dev/design/apps.md).

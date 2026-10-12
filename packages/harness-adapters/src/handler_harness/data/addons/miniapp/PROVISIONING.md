# Mini apps addon — provisioning

Nothing to provision: the addon brings Deno and the skill, and needs no account.

1. `handler image rebuild addon:miniapp` (or Settings → Addons → Rebuild).
2. A binding, `~/.config/handler-ai/bindings/miniapp.toml`:

   ```toml
   apiVersion = "handler.binding/v1"
   addon = "miniapp"
   ```

3. An agent on the app's folder that selects it, with a filtered network (the addon adds
   `registry.npmjs.org` and `jsr.io`, for the UI's build).
4. When the agent is done: Apps page → Add (the folder) → Deploy. Only you deploy
   (docs/dev/design/miniapps.md).

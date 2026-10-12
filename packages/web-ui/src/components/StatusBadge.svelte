<script lang="ts">
  import { Badge } from "$lib/components/ui/badge";

  let { status }: { status: string } = $props();

  // plain words for the settings people choose (the raw values stay in the files and the API)
  const labels: Record<string, string> = {
    container: "sandboxed",
    nested: "runs containers",
    privileged: "privileged sandbox",
    display: "shows windows",
    none: "no network",
    filtered: "filtered network",
    open: "open network",
    "log-only": "log only",
    enforce: "enforced",
    ask: "asks first",
    "accept-edits": "auto edits",
    bypass: "auto-approve",
    "preset-locked": "Locked down",
    "preset-guarded": "Guarded",
    "preset-open": "Open",
  };

  const tone = $derived(
    ["succeeded", "completed", "ok", "enforce", "container", "strict", "filtered", "none", "on", "preset-locked", "preset-guarded"].includes(status)
      ? "bg-ok"
      : ["failed", "timed_out", "privileged", "open"].includes(status)
        ? "bg-danger"
        : ["running", "in_progress", "pending", "attention", "log-only", "cancelled", "nested", "bypass", "preset-open"].includes(status)
          ? "bg-warn"
          : "bg-muted-foreground",
  );
</script>

<Badge variant="outline" class="gap-1.5 font-normal text-muted-foreground">
  <span class="size-1.5 shrink-0 rounded-full {tone}" aria-hidden="true"></span>{labels[status] ?? status.replaceAll("_", " ")}
</Badge>

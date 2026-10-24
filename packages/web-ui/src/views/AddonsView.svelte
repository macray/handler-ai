<script lang="ts">
  // The addons (G) and their configurations (D.15), in the library: what agents are given to
  // reach a system (a shop, a browser), as skills and knowledge are. `install`: from Discover,
  // that source's addon's preview open (D.26).
  import AddonLibrary from "../components/AddonLibrary.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";

  let { install }: { install?: string } = $props();
</script>

<PageHeader titled title="Addons" />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-5 px-8 py-10" data-testid="addons-page">
    <PageTitle title="Addons" />
    <AddonLibrary {install} />
  </div>
</div>

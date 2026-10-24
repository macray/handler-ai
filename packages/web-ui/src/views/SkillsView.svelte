<script lang="ts">
  // The skill library (D.17), in the main menu: what agents load when a task calls for it; then
  // the agents Handler asks to review and write skills (D.18).
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import SkillAgents from "../components/SkillAgents.svelte";
  import SkillLibrary from "../components/SkillLibrary.svelte";
</script>

<PageHeader titled title="Skills" />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-5 px-8 py-10" data-testid="skills-page">
    <PageTitle title="Skills" />
    <SkillLibrary />
    <SkillAgents />
  </div>
</div>

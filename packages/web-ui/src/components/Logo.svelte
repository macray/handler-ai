<script lang="ts">
  // The Handler mark (branding/speech-case.svg): drawn in the text color, its dots in the theme's primary.
  let { class: className = "" }: { class?: string } = $props();
</script>

<svg class={className} viewBox="0 0 64 64" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M23 20 V14 a4 4 0 0 1 4 -4 h10 a4 4 0 0 1 4 4 v6" />
  <path d="M14 20 H50 a8 8 0 0 1 8 8 V44 a8 8 0 0 1 -8 8 H28 L17 60 V52 H14 a8 8 0 0 1 -8 -8 V28 a8 8 0 0 1 8 -8 Z" />
  <g fill="var(--primary)" stroke="none">
    <circle cx="22" cy="36" r="3.5" />
    <circle cx="32" cy="36" r="3.5" />
    <circle cx="42" cy="36" r="3.5" />
  </g>
</svg>

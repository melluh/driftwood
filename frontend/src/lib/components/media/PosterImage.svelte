<!-- A rounded poster with a subtle frame; width comes from the parent. -->
<script lang="ts">
	import TmdbImage from './TmdbImage.svelte';

	let {
		path,
		title,
		sizes,
		eager = false
	}: { path: string | null | undefined; title: string; sizes: string; eager?: boolean } = $props();
</script>

<div class="poster">
	<TmdbImage {path} kind="poster" alt="Poster for {title}" {sizes} {eager} radius="md" />
</div>

<style>
	.poster {
		width: 100%;
		border-radius: var(--radius-md);
		box-shadow:
			0 0 0 1px var(--color-border),
			var(--shadow-lg);
	}
</style>

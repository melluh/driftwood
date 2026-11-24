<script lang="ts">
	import FeaturedCarousel from '#lib/components/home/FeaturedCarousel.svelte';
	import MediaRow from '#lib/components/home/MediaRow.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<FeaturedCarousel items={data.home.featured} />

<div class="rows">
	{#each data.home.rows as row (row.id)}
		<MediaRow title={row.title} items={row.items} />
	{/each}
</div>

<style>
	/* Rows slide up into the hero's faded bottom edge */
	.rows {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-8);
		margin-top: calc(-1 * var(--space-4));
		padding-bottom: var(--space-12);
	}
</style>

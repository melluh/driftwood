<script lang="ts">
	import type { CastMember } from '#lib/api/client.ts';
	import CastCard from './CastCard.svelte';

	let { cast }: { cast: CastMember[] } = $props();
</script>

<ul class="cast-list">
	{#each cast as member (member.id)}
		<li><CastCard {member} /></li>
	{/each}
</ul>

<style>
	.cast-list {
		display: grid;
		grid-auto-flow: column;
		grid-auto-columns: 8rem;
		gap: var(--space-4);
		margin: 0;
		padding: 0 0 var(--space-4);
		list-style: none;
		overflow-x: auto;
		scroll-snap-type: x proximity;
		scrollbar-width: thin;
		scrollbar-color: var(--color-border) transparent;
	}

	li {
		scroll-snap-align: start;
	}
</style>

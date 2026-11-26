<script lang="ts">
	import type { CastMember } from '#lib/api/client.ts';
	import HorizontalScroller from '../ui/HorizontalScroller.svelte';
	import CastCard from './CastCard.svelte';

	let { cast }: { cast: CastMember[] } = $props();
</script>

<div class="cast">
	<HorizontalScroller
		items={cast}
		key={(member: CastMember) => member.id}
		label="Cast"
		itemWidth="8rem"
		gutter="var(--content-inset)"
	>
		{#snippet item(member)}
			<CastCard {member} />
		{/snippet}
	</HorizontalScroller>
</div>

<style>
	/* Break out of the section's padding: full-bleed like the home rows, with
	   the content inset as the gutter where the edge fades and nav buttons sit */
	.cast {
		margin-inline: calc(-1 * var(--content-inset));
	}
</style>

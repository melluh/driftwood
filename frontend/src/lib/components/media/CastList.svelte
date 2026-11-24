<script lang="ts">
	import type { CastMember } from '#lib/api/client.ts';
	import HorizontalScroller from '../ui/HorizontalScroller.svelte';
	import CastCard from './CastCard.svelte';

	let { cast }: { cast: CastMember[] } = $props();
</script>

<HorizontalScroller
	items={cast}
	key={(member: CastMember) => member.id}
	label="Cast"
	itemWidth="8rem"
>
	{#snippet item(member)}
		<CastCard {member} />
	{/snippet}
</HorizontalScroller>

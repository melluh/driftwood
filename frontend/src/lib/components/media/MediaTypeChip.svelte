<script lang="ts">
	import Chip from '../ui/Chip.svelte';
	import Icon from '../ui/Icon.svelte';
	import { mediaTypeLabel } from '#lib/media/format.ts';
	import type { MediaType } from '#lib/api/client.ts';

	let { type }: { type: MediaType } = $props();
</script>

<Chip>
	<Icon name={type === 'tv' ? 'tv' : 'film'} size="1em" />
	{mediaTypeLabel(type)}
</Chip>

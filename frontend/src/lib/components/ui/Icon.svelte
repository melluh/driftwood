<script lang="ts">
	import { ICONS, type IconName } from './icons.ts';

	let {
		name,
		size = '1.25em',
		label
	}: {
		name: IconName;
		size?: string;
		/** Accessible label; omit for decorative icons. */
		label?: string;
	} = $props();
</script>

<svg
	viewBox="0 0 24 24"
	width={size}
	height={size}
	fill="none"
	stroke="currentColor"
	stroke-width="1.75"
	stroke-linecap="round"
	stroke-linejoin="round"
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : true}
>
	{#each ICONS[name] as d (d)}
		<path {d} />
	{/each}
</svg>

<style>
	svg {
		flex-shrink: 0;
	}
</style>

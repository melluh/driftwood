<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.ts';

	let {
		variant = 'primary',
		icon,
		children,
		...rest
	}: HTMLButtonAttributes & {
		variant?: 'primary' | 'secondary';
		icon?: IconName;
		children: Snippet;
	} = $props();
</script>

<button type="button" class="button {variant}" {...rest}>
	{#if icon}<Icon name={icon} />{/if}
	{@render children()}
</button>

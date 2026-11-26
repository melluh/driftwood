<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.ts';

	let {
		href,
		variant = 'primary',
		icon,
		onclick,
		children
	}: {
		/** An already-resolved href. */
		href: string;
		variant?: 'primary' | 'secondary';
		icon?: IconName;
		onclick?: (event: MouseEvent & { currentTarget: HTMLAnchorElement }) => void;
		children: Snippet;
	} = $props();
</script>

<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- callers pass resolved hrefs -->
<a {href} class="button {variant}" {onclick}>
	{#if icon}<Icon name={icon} />{/if}
	{@render children()}
</a>

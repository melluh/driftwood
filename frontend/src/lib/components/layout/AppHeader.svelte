<script lang="ts">
	import Logo from '../brand/Logo.svelte';
	import SearchButton from '../search/SearchButton.svelte';

	let { onsearch }: { onsearch: () => void } = $props();

	let scrollY = $state(0);
	const scrolled = $derived(scrollY > 8);
</script>

<svelte:window bind:scrollY />

<header class:scrolled>
	<Logo />
	<SearchButton onclick={onsearch} />
</header>

<style>
	header {
		position: fixed;
		inset: 0 0 auto;
		z-index: 10;
		height: var(--header-height);
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 var(--content-inset);
		background: linear-gradient(to bottom, oklch(from var(--color-bg) l c h / 0.85), transparent);
		transition:
			background var(--duration-slow),
			backdrop-filter var(--duration-slow);
	}

	/* Solid once content scrolls underneath */
	.scrolled {
		background: oklch(from var(--color-bg) l c h / 0.88);
		backdrop-filter: blur(12px);
		box-shadow: 0 1px 0 var(--color-border);
	}
</style>

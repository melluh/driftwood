<script lang="ts">
	import Logo from '../brand/Logo.svelte';
	import SearchButton from '../search/SearchButton.svelte';

	let { onsearch }: { onsearch: () => void } = $props();
</script>

<header>
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
		padding: 0 var(--page-gutter);
		background: linear-gradient(to bottom, oklch(from var(--color-bg) l c h / 0.85), transparent);
	}
</style>

<script lang="ts">
	import type { CurrentUser } from '#lib/api/client.ts';
	import Logo from '../brand/Logo.svelte';
	import SearchButton from '../search/SearchButton.svelte';
	import UserMenu from '../user/UserMenu.svelte';

	let { user, onsearch }: { user: CurrentUser; onsearch: () => void } = $props();

	let scrollY = $state(0);
	const scrolled = $derived(scrollY > 8);
</script>

<svelte:window bind:scrollY />

<header class:scrolled>
	<Logo />
	<div class="actions">
		<SearchButton onclick={onsearch} />
		<UserMenu {user} />
	</div>
</header>

<style>
	header {
		position: fixed;
		inset: 0 0 auto;
		z-index: 10;
		view-transition-name: app-header;
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

	/* Under the search overlay: stay part of the page so the overlay's screen
	   isn't captured with the header floating over it */
	:global(html:has(dialog[open])) header {
		view-transition-name: none;
	}

	/* Solid once content scrolls underneath */
	.scrolled {
		background: oklch(from var(--color-bg) l c h / 0.88);
		backdrop-filter: blur(12px);
		box-shadow: 0 1px 0 var(--color-border);
	}

	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
</style>

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
		padding-inline: var(--content-inset);
		background: linear-gradient(to bottom, oklch(from var(--color-bg) l c h / 0.85), transparent);
	}

	/*
	 * The solid background lives on its own layer and fades in once content
	 * scrolls underneath: gradients can't be transitioned, so swapping the
	 * header's own background would just pop.
	 */
	header::before {
		content: '';
		position: absolute;
		inset: 0;
		z-index: -1;
		background: oklch(from var(--color-bg) l c h / 0.88);
		backdrop-filter: blur(12px);
		box-shadow: 0 1px 0 var(--color-border);
		opacity: 0;
		transition: opacity var(--duration-slow) var(--ease-out);
	}

	.scrolled::before {
		opacity: 1;
	}

	/* Under the search overlay: stay part of the page so the overlay's screen
	   isn't captured with the header floating over it */
	:global(html:has(dialog[open])) header {
		view-transition-name: none;
	}

	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-6);
	}
</style>

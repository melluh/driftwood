<script lang="ts">
	import Logo from '#lib/components/brand/Logo.svelte';
	import Icon from '#lib/components/ui/Icon.svelte';
	import { getSearchOverlay } from '#lib/search/overlay.svelte.ts';

	const overlay = getSearchOverlay();
</script>

<section class="landing">
	<Logo size="lg" href={null} />
	<p>Find any movie or TV series, from blockbusters to forgotten gems.</p>
	<button type="button" class="cta" onclick={overlay.open}>
		<Icon name="search" />
		<span>Search movies and TV</span>
		<kbd>/</kbd>
	</button>
</section>

<style>
	.landing {
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-6);
		padding: var(--page-gutter);
		text-align: center;
		background: radial-gradient(
			ellipse at 50% 40%,
			oklch(from var(--color-accent) 30% 0.04 h / 0.35),
			transparent 60%
		);
	}

	p {
		color: var(--color-text-muted);
		font-size: var(--text-lg);
		max-width: 32rem;
	}

	.cta {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: min(100%, 32rem);
		padding: var(--space-4) var(--space-6);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
		color: var(--color-text-faint);
		font-size: var(--text-lg);
		cursor: pointer;
		transition: border-color var(--duration-fast);
	}

	.cta:hover {
		border-color: var(--color-accent);
	}

	.cta span {
		flex: 1;
		text-align: left;
	}

	kbd {
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
	}
</style>

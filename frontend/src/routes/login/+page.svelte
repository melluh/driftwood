<script lang="ts">
	import PosterWall from '#lib/components/auth/PosterWall.svelte';
	import Logo from '#lib/components/brand/Logo.svelte';
	import Icon from '#lib/components/ui/Icon.svelte';
	import LinkButton from '#lib/components/ui/LinkButton.svelte';
	import { oauthLoginHref } from '#lib/auth/session.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const ERRORS: Record<string, string> = {
		denied: 'Sign-in was cancelled.',
		failed: 'Sign-in failed. Please try again.',
		not_configured: 'Sign-in isn’t set up on this server yet.'
	};

	const message = $derived(
		!data.config.configured
			? ERRORS.not_configured
			: data.error
				? (ERRORS[data.error] ?? ERRORS.failed)
				: null
	);
</script>

<svelte:head>
	<title>Sign in · Driftwood</title>
</svelte:head>

<div class="login">
	<PosterWall posters={data.posters} />
	<div class="shade" aria-hidden="true"></div>

	<div class="card">
		<div class="brand"><Logo size="lg" href={null} /></div>

		<div class="copy">
			<h1>Welcome back</h1>
			<p>Sign in to continue to Driftwood.</p>
		</div>

		{#if message}
			<p class="error" role="alert">
				<Icon name="alert" />
				{message}
			</p>
		{/if}

		{#if data.config.configured}
			<!-- The OAuth flow lives on the backend: a full page load, not a client-side route. -->
			<div class="action" data-sveltekit-reload>
				<LinkButton href={oauthLoginHref(data.next)} icon="log-in">
					Log in with {data.config.provider_name}
				</LinkButton>
			</div>
		{/if}
	</div>

	{#if data.posters.length}
		<p class="credit">Posters from TMDB</p>
	{/if}
</div>

<style>
	.login {
		position: relative;
		isolation: isolate;
		overflow: hidden;
		min-height: 100dvh;
		display: grid;
		place-items: center;
		padding: var(--space-8) var(--page-gutter);
		background: var(--color-bg);
	}

	/* Darkest behind the card, so the wall frames it rather than competing with it */
	.shade {
		position: absolute;
		inset: 0;
		background:
			radial-gradient(
				60rem 40rem at 50% -10%,
				oklch(from var(--color-accent) l c h / 0.14),
				transparent 70%
			),
			radial-gradient(
				ellipse 34rem 30rem at 50% 50%,
				oklch(from var(--color-bg) l c h / 0.92) 20%,
				oklch(from var(--color-bg) l c h / 0.55) 70%,
				oklch(from var(--color-bg) l c h / 0.35)
			),
			linear-gradient(to bottom, var(--color-bg), transparent 22%, transparent 78%, var(--color-bg));
	}

	.card {
		position: relative;
		width: min(27rem, 100%);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-6);
		padding: var(--space-12) clamp(var(--space-6), 5vw, var(--space-8)) var(--space-8);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: oklch(from var(--color-surface) l c h / 0.72);
		backdrop-filter: blur(20px) saturate(1.2);
		box-shadow:
			inset 0 1px 0 oklch(100% 0 0 / 0.06),
			var(--shadow-lg);
		text-align: center;
		animation: rise 700ms var(--ease-emphasized) both;
	}

	/* A small brand mark above the heading; its plank bobs gently on the current */
	.brand :global(.logo) {
		font-size: 1.375rem;
		color: var(--color-text-muted);
	}

	.brand :global(svg) {
		animation: bob 6s ease-in-out infinite;
	}

	.copy {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	h1 {
		font-family: var(--font-display);
		font-size: 2.25rem;
		font-weight: 600;
		line-height: 1.15;
		color: var(--color-accent-strong);
	}

	.copy p {
		color: var(--color-text-muted);
		text-wrap: balance;
	}

	.error {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-4);
		border-radius: var(--radius-md);
		background: oklch(from var(--color-danger) l c h / 0.12);
		color: var(--color-danger);
		font-size: var(--text-sm);
	}

	/* Extra room between the copy and the button */
	.action {
		display: flex;
		justify-content: center;
		margin-top: var(--space-4);
	}

	.credit {
		position: absolute;
		bottom: var(--space-4);
		left: 0;
		right: 0;
		text-align: center;
		font-size: var(--text-xs);
		color: var(--color-text-faint);
	}

	@keyframes rise {
		from {
			opacity: 0;
			transform: translateY(1rem) scale(0.98);
		}
	}

	@keyframes bob {
		0%,
		100% {
			transform: translateY(0) rotate(0deg);
		}
		50% {
			transform: translateY(-0.08em) rotate(-4deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.card,
		.brand :global(svg) {
			animation: none;
		}
	}
</style>

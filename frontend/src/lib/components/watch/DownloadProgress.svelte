<script lang="ts">
	import { untrack } from 'svelte';
	import { fade } from 'svelte/transition';
	import type { DownloadStatus } from '#lib/api/client.ts';
	import { downloadHeadline, formatEta } from '#lib/watch/download.ts';
	import { EtaEstimator } from '#lib/watch/eta.ts';
	import Button from '../ui/Button.svelte';
	import Icon from '../ui/Icon.svelte';
	import InlineAlert from '../ui/InlineAlert.svelte';
	import PulseRings from '../ui/PulseRings.svelte';

	let {
		download,
		cancelling = false,
		oncancel
	}: {
		download: DownloadStatus;
		cancelling?: boolean;
		oncancel: () => void;
	} = $props();

	/** Length of the spinning arc, in hundredths of the ring. */
	const SPIN_LENGTH = 22;
	const SPIN_MS = 1400;
	/** Bounds on how long the spinner takes to settle into the progress arc. */
	const SETTLE_MIN_MS = 500;
	const SETTLE_MAX_MS = 1600;

	const finished = $derived(download.state === 'importing' || download.state === 'completed');
	/** Bytes have arrived: from here on there's real progress to show. */
	const started = $derived(download.downloaded > 0 || download.progress > 0);
	const indeterminate = $derived(download.state === 'downloading' && !started);
	const fraction = $derived(finished ? 1 : Math.min(1, Math.max(0, download.progress)));
	const percent = $derived(Math.floor(fraction * 100));
	const arcLength = $derived(indeterminate ? SPIN_LENGTH : fraction * 100);
	const moving = $derived(
		download.state !== 'downloading' ||
			download.activity === 'downloading' ||
			download.activity === 'connecting'
	);

	// Time left, once the estimate has settled (see EtaEstimator).
	const estimator = new EtaEstimator();
	let etaSeconds = $state<number | null>(null);
	$effect(() => {
		const { state, downloaded, size, activity } = download;
		etaSeconds =
			state === 'downloading'
				? estimator.update(performance.now(), downloaded, size ?? 0, activity === 'downloading')
				: null;
	});

	/** The small line under the percentage: time left, or what's going on instead. */
	const caption = $derived.by(() => {
		if (download.state === 'importing') return 'Adding to library';
		if (download.state === 'completed') return 'Ready';
		if (download.state !== 'downloading') return null;
		if (!started) return 'Starting';
		if (download.activity === 'paused') return 'Paused';
		if (download.activity === 'checking') return 'Checking files';
		if (download.activity === 'stalled') return 'Waiting for peers';
		if (etaSeconds !== null) return formatEta(etaSeconds);
		return 'Estimating…';
	});
	const settled = $derived(etaSeconds !== null);
	/** Fade the caption in when it changes kind, not each time the minutes tick down. */
	const captionKind = $derived(settled && download.state === 'downloading' ? 'eta' : caption);
	const label = $derived(
		[downloadHeadline(download), indeterminate ? null : `${percent}%`, caption]
			.filter(Boolean)
			.join(', ')
	);

	// One arc does both jobs: it spins while there's nothing to measure, then glides to
	// 12 o'clock and stretches to the progress, leaving at the speed it was spinning.
	let spinner = $state<SVGGElement>();
	let arc = $state<SVGCircleElement>();
	let settling = $state(false);
	let spin: Animation | null = null;

	function reducedMotion(): boolean {
		return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
	}

	function settle(group: SVGGElement, circle: SVGCircleElement, angle: number, length: number) {
		const speed = 360 / SPIN_MS; // degrees per ms
		// Glide on to 12 o'clock (at least a quarter turn, so it never stops dead), slowing down
		// steadily from the spin speed: covering `travel` that way takes 2 × travel / speed.
		let travel = 360 - angle;
		if (travel < 90) travel += 360;
		const duration = Math.min(SETTLE_MAX_MS, Math.max(SETTLE_MIN_MS, (2 * travel) / speed));
		// A cubic curve whose start slope matches the spin speed (2 = a pure ease-out; less when
		// the duration is capped) and which comes to rest at the end.
		const slope = (speed * duration) / travel;
		const easing = `cubic-bezier(${1 / 3}, ${(slope / 3).toFixed(3)}, ${2 / 3}, 1)`;
		settling = true;
		group.animate(
			[{ transform: `rotate(${angle}deg)` }, { transform: `rotate(${angle + travel}deg)` }],
			{ duration, easing }
		);
		const stretch = circle.animate(
			[{ strokeDasharray: `${SPIN_LENGTH} 100` }, { strokeDasharray: `${length} 100` }],
			{ duration, easing: 'cubic-bezier(0.4, 0, 0.2, 1)' }
		);
		stretch.onfinish = stretch.oncancel = () => (settling = false);
	}

	$effect(() => {
		const spinning = indeterminate;
		const group = spinner;
		const circle = arc;
		if (!group || !circle) return;
		untrack(() => {
			if (spinning) {
				if (!spin && !reducedMotion()) {
					spin = group.animate([{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], {
						duration: SPIN_MS,
						iterations: Infinity
					});
				}
				return;
			}
			if (!spin) return;
			const elapsed = Number(spin.currentTime ?? 0) % SPIN_MS;
			spin.cancel();
			spin = null;
			settle(group, circle, (elapsed / SPIN_MS) * 360, arcLength);
		});
	});

	$effect(() => () => spin?.cancel());
</script>

<div class="progress" role="status" aria-live="polite">
	<div
		class="dial"
		role="progressbar"
		aria-label={label}
		aria-valuemin={0}
		aria-valuemax={100}
		aria-valuenow={indeterminate ? undefined : percent}
	>
		<!-- The same ripple as "Checking for torrents", while data is (about to be) flowing. -->
		<PulseRings from={0.8} to={1.25} peak={0.45} active={moving} />
		<svg viewBox="0 0 120 120" aria-hidden="true">
			<circle class="track" cx="60" cy="60" r="56" pathLength="100" />
			<g class="spinner" bind:this={spinner}>
				<circle
					bind:this={arc}
					class="arc"
					class:settling
					cx="60"
					cy="60"
					r="56"
					pathLength="100"
					style:stroke-dasharray="{arcLength} 100"
				/>
			</g>
		</svg>
		<span class="core" aria-hidden="true">
			<span class="main">
				{#if finished}
					<span class="face" in:fade={{ duration: 300 }}><Icon name="film" size="2.25rem" /></span>
				{:else if indeterminate}
					<span class="face"><Icon name="download" size="2.25rem" /></span>
				{:else}
					<span class="face percent" in:fade={{ duration: 300 }}>{percent}<small>%</small></span>
				{/if}
			</span>
			<!-- Always there, so the percentage never moves when the caption appears. -->
			<span class="caption" class:settled>
				{#key captionKind}
					<span in:fade={{ duration: 250 }}>{caption ?? '\u00a0'}</span>
				{/key}
			</span>
		</span>
	</div>

	<!-- Keeps its space when hidden, so nothing moves when cancelling stops being possible. -->
	<div class="actions" class:hidden={download.state !== 'downloading' || !download.can_cancel}>
		<Button
			variant="secondary"
			icon="close"
			disabled={cancelling || !download.can_cancel || download.state !== 'downloading'}
			onclick={oncancel}
		>
			{cancelling ? 'Cancelling…' : 'Cancel download'}
		</Button>
	</div>

	{#if download.error}
		<div class="warning"><InlineAlert>{download.error}</InlineAlert></div>
	{/if}
</div>

<style>
	.progress {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-8);
		text-align: center;
	}

	.dial {
		position: relative;
		display: grid;
		place-items: center;
		width: 13rem;
		height: 13rem;
	}

	svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		transform: rotate(-90deg);
		overflow: visible;
	}

	circle {
		fill: none;
		stroke-width: 3.5;
	}

	.track {
		stroke: var(--color-accent-soft);
	}

	.spinner {
		transform-origin: 60px 60px;
	}

	.arc {
		stroke: var(--color-accent);
		stroke-linecap: round;
		transition: stroke-dasharray 1s linear;
	}

	/* The settle animation drives the arc; a transition would win over it in the cascade. */
	.arc.settling {
		transition: none;
	}

	.core {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		width: 10rem;
		height: 10rem;
		border-radius: var(--radius-full);
		background: var(--color-accent-soft);
		color: var(--color-accent-strong);
	}

	.main {
		display: grid;
		place-items: center;
		height: 3.25rem;
	}

	.face {
		display: flex;
		align-items: center;
		justify-content: center;
		grid-area: 1 / 1;
	}

	.percent {
		align-items: baseline;
		font-family: var(--font-display);
		font-size: 2.75rem;
		font-weight: 600;
		line-height: 1;
		font-variant-numeric: tabular-nums;
		color: var(--color-text);
	}

	.percent small {
		margin-left: 0.05em;
		font-size: 0.45em;
		color: var(--color-text-muted);
	}

	.caption {
		display: grid;
		max-width: 8.5rem;
		font-size: var(--text-xs);
		line-height: 1.4;
		white-space: nowrap;
		color: var(--color-text-faint);
		font-variant-numeric: tabular-nums;
	}

	.caption > span {
		grid-area: 1 / 1;
	}

	.caption.settled {
		color: var(--color-text-muted);
	}

	@media (prefers-reduced-motion: reduce) {
		.arc {
			transition: none;
		}
	}

	.actions {
		transition:
			opacity var(--duration-fast),
			visibility var(--duration-fast);
	}

	.actions.hidden {
		visibility: hidden;
		opacity: 0;
	}

	.warning {
		max-width: 30rem;
	}
</style>

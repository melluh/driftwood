<!--
	The player's timeline: what's played, what's buffered, and a time preview
	under the pointer (with a thumbnail when the file has trickplay sheets).
	Dragging only previews; the seek happens on release, so scrubbing doesn't
	make the server cut segments for every position passed.

	Pointer positions map linearly across the whole bar, the same way for the
	preview, the thumb and the seek. (A native range input maps clicks across
	its width minus the thumb's, which put seeks up to half a thumb, tens of
	seconds on a long film, away from the time previewed.) The input stays for
	keyboard and screen-reader use only.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import type { PlaybackTrickplay } from '#lib/api/client.ts';
	import { formatTime } from '#lib/playback/labels.ts';

	let {
		currentTime,
		duration,
		buffered,
		trickplay = null,
		onseek
	}: {
		currentTime: number;
		duration: number;
		buffered: { start: number; end: number }[];
		trickplay?: PlaybackTrickplay | null;
		onseek: (time: number) => void;
	} = $props();

	let scrubbing = $state<number | null>(null);
	let hover = $state<{ time: number; x: number } | null>(null);
	let width = $state(0);
	let dragging = $state(false);
	let bar: HTMLDivElement;

	const shown = $derived(scrubbing ?? currentTime);
	const previewTime = $derived(scrubbing ?? hover?.time ?? null);

	/** Which sheet holds the thumbnail for a time, and where on it (while that sheet is ready). */
	function tile(time: number) {
		if (!trickplay || trickplay.count < 1) return null;
		const perSheet = trickplay.columns * trickplay.rows;
		const index = Math.min(Math.max(Math.floor(time / trickplay.interval), 0), trickplay.count - 1);
		const position = index % perSheet;
		const sheet = Math.floor(index / perSheet);
		if (!trickplay.ready[sheet]) return null;
		return {
			sheet,
			column: position % trickplay.columns,
			row: Math.floor(position / trickplay.columns)
		};
	}

	const thumbnail = $derived(previewTime === null ? null : tile(previewTime));

	// Sheets are fetched while previewing, the neighbours too since scrubbing
	// usually carries on into them. A thumbnail shows once its whole sheet is in,
	// rather than as a half-drawn grid; a sheet that fails stays blank. Sheets
	// still being made are skipped until they're ready.
	/** Sheet index → whether it has finished loading. */
	const sheets = new SvelteMap<number, boolean>();
	/** The session's first sheet URL: the same while more sheets become ready. */
	const source = $derived(trickplay?.sheets[0] ?? null);
	$effect(() => {
		if (!trickplay || !thumbnail) return;
		const { sheets: urls, ready } = trickplay;
		const loading = source;
		for (const index of [thumbnail.sheet, thumbnail.sheet + 1, thumbnail.sheet - 1]) {
			if (!ready[index] || untrack(() => sheets.has(index))) continue;
			sheets.set(index, false);
			const image = new Image();
			image.onload = () => {
				if (source === loading) sheets.set(index, true);
			};
			image.src = urls[index];
		}
	});
	$effect(() => {
		void source;
		return () => sheets.clear();
	});

	/** Background offset of a tile, as a percentage of the room the sheet can move. */
	const offset = (index: number, count: number) => (count > 1 ? (index / (count - 1)) * 100 : 0);
	const percent = (time: number) => (duration > 0 ? Math.min(100, (time / duration) * 100) : 0);

	/** The time under the pointer, and where that is on the bar. */
	function at(event: PointerEvent) {
		const rect = bar.getBoundingClientRect();
		const x = Math.min(Math.max(event.clientX - rect.left, 0), rect.width);
		return { x, time: rect.width > 0 ? (x / rect.width) * duration : 0 };
	}

	function onpointerdown(event: PointerEvent) {
		if (event.button !== 0 || !(duration > 0)) return;
		event.preventDefault();
		bar.setPointerCapture(event.pointerId);
		dragging = true;
		hover = at(event);
		scrubbing = hover.time;
	}

	function onpointermove(event: PointerEvent) {
		hover = at(event);
		if (dragging) scrubbing = hover.time;
	}

	function onpointerup(event: PointerEvent) {
		if (!dragging) return;
		dragging = false;
		const { time } = at(event);
		scrubbing = null;
		if (event.pointerType !== 'mouse') hover = null;
		onseek(time);
	}

	function onpointercancel() {
		dragging = false;
		scrubbing = null;
		hover = null;
	}

	function commit(event: Event) {
		const value = Number((event.currentTarget as HTMLInputElement).value);
		scrubbing = null;
		onseek(value);
	}
</script>

<div
	class="seek"
	class:dragging
	role="presentation"
	bind:this={bar}
	bind:clientWidth={width}
	{onpointerdown}
	{onpointermove}
	{onpointerup}
	{onpointercancel}
	onpointerleave={() => {
		if (!dragging) hover = null;
	}}
	style:--played="{percent(shown)}%"
>
	<div class="track" aria-hidden="true">
		{#each buffered as range (range.start)}
			<span
				class="buffered"
				style:left="{percent(range.start)}%"
				style:width="{percent(range.end) - percent(range.start)}%"
			></span>
		{/each}
		<span class="played"></span>
	</div>
	<span class="thumb" aria-hidden="true"></span>
	<input
		type="range"
		min="0"
		max={duration || 0}
		step="any"
		value={shown}
		aria-label="Seek"
		aria-valuetext="{formatTime(shown)} of {formatTime(duration)}"
		oninput={(event) => (scrubbing = Number(event.currentTarget.value))}
		onchange={commit}
	/>
	{#if previewTime !== null}
		{@const x = scrubbing !== null ? (percent(scrubbing) / 100) * width : (hover?.x ?? 0)}
		<div
			class="preview"
			class:with-thumbnail={trickplay && thumbnail}
			style:--thumbnail-width={trickplay ? `${trickplay.width}px` : null}
			style:left="clamp(calc(var(--preview-width) / 2), {x}px, calc(100% - var(--preview-width) /
			2))"
		>
			{#if trickplay && thumbnail}
				<span
					class="thumbnail"
					style:aspect-ratio="{trickplay.width} / {trickplay.height}"
					style:background-image={sheets.get(thumbnail.sheet)
						? `url("${trickplay.sheets[thumbnail.sheet]}")`
						: null}
					style:background-size="{trickplay.columns * 100}% {trickplay.rows * 100}%"
					style:background-position="{offset(thumbnail.column, trickplay.columns)}% {offset(
						thumbnail.row,
						trickplay.rows
					)}%"
				></span>
			{/if}
			<span class="time">{formatTime(previewTime)}</span>
		</div>
	{/if}
</div>

<style>
	.seek {
		position: relative;
		height: 1.5rem;
		display: flex;
		align-items: center;
		cursor: pointer;
		touch-action: none;
	}

	.track {
		position: absolute;
		inset: 50% 0 auto;
		height: 0.25rem;
		transform: translateY(-50%);
		border-radius: var(--radius-full);
		background: oklch(100% 0 0 / 0.2);
		overflow: hidden;
		transition: height var(--duration-fast);
	}

	.seek:hover .track,
	.seek:focus-within .track {
		height: 0.4rem;
	}

	.buffered,
	.played {
		position: absolute;
		inset-block: 0;
	}

	.buffered {
		background: oklch(100% 0 0 / 0.3);
	}

	.played {
		left: 0;
		width: var(--played);
		background: var(--color-accent);
	}

	input {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		margin: 0;
		opacity: 0;
		pointer-events: none;
	}

	.thumb {
		position: absolute;
		top: 50%;
		left: var(--played);
		width: 0.875rem;
		height: 0.875rem;
		border-radius: var(--radius-full);
		background: var(--color-accent-strong);
		box-shadow: 0 0 0 4px oklch(from var(--color-accent) l c h / 0.25);
		transform: translate(-50%, -50%) scale(0);
		transition: transform var(--duration-fast);
		pointer-events: none;
	}

	.seek:hover .thumb,
	.seek.dragging .thumb,
	.seek:has(input:focus-visible) .thumb {
		transform: translate(-50%, -50%) scale(1);
	}

	.seek:has(input:focus-visible) .track {
		outline: 2px solid var(--color-accent);
		outline-offset: 3px;
	}

	.preview {
		--preview-width: 3.5rem;
		position: absolute;
		bottom: calc(100% + var(--space-1));
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
		transform: translateX(-50%);
		pointer-events: none;
	}

	.preview.with-thumbnail {
		--preview-width: min(var(--thumbnail-width), 14rem, 40vw);
		bottom: calc(100% + var(--space-2));
	}

	.thumbnail {
		width: var(--preview-width);
		border-radius: var(--radius-md);
		background-color: oklch(0% 0 0 / 0.8);
		background-repeat: no-repeat;
		box-shadow:
			0 0 0 1px oklch(100% 0 0 / 0.15),
			var(--shadow-lg);
	}

	.time {
		padding: 0.125rem var(--space-2);
		border-radius: var(--radius-sm);
		background: oklch(0% 0 0 / 0.8);
		color: #fff;
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}
</style>

<!--
	Full-screen player for a library playback session: custom controls that
	fade while watching, audio / subtitle / version menus, keyboard shortcuts,
	and subtitles drawn above the controls instead of under them.
-->
<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { api, type PlaybackSession, type PlaybackVersion } from '#lib/api/client.ts';
	import Button from '#lib/components/ui/Button.svelte';
	import Icon from '#lib/components/ui/Icon.svelte';
	import IconButton from '#lib/components/ui/IconButton.svelte';
	import type { IconName } from '#lib/components/ui/icons.ts';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import { attach, type Engine } from '#lib/playback/engine.ts';
	import {
		audioDetail,
		audioName,
		formatTime,
		subtitleName,
		versionName,
		versionSize
	} from '#lib/playback/labels.ts';
	import {
		loadPreferences,
		pickAudio,
		pickSubtitles,
		savePreferences
	} from '#lib/playback/preferences.ts';
	import { SubtitleRenderer } from '#lib/playback/subtitles.ts';
	import PlayerMenu, { type MenuOption } from './PlayerMenu.svelte';
	import SeekBar from './SeekBar.svelte';

	let {
		session,
		versions,
		title,
		detail,
		startAt = 0,
		onclose,
		onversion,
		onretry,
		onfallback,
		onready,
		onprogress
	}: {
		session: PlaybackSession;
		versions: PlaybackVersion[];
		title: string;
		detail?: string | null;
		/** Seconds into the title to start at (after switching versions or a retry). */
		startAt?: number;
		onclose: () => void;
		onversion: (fileId: number, at: number) => void;
		/** Start a new session at this position. */
		onretry: (at: number) => void;
		/** Give up on the library copy and search for a release. */
		onfallback: (reason: string) => void;
		/**
		 * The player has something to show: the first frame is playing, or it
		 * needs the viewer (autoplay was blocked, playback failed). Until then it
		 * stays blank, for a curtain to cover.
		 */
		onready?: () => void;
		/** Where playback is, every few seconds while playing and whenever it stops. */
		onprogress?: (position: number, duration: number) => Promise<void> | void;
	} = $props();

	const SKIP_SECONDS = 10;
	const IDLE_MS = 3000;
	const PROGRESS_INTERVAL_MS = 10_000;
	const TRICKPLAY_POLL_MS = 3000;
	/** With no new sheet for this long, something's slow: ask only every `TRICKPLAY_SLOW_POLL_MS`. */
	const TRICKPLAY_STALL_MS = 60_000;
	const TRICKPLAY_SLOW_POLL_MS = 60_000;

	// Read once: a new session remounts the player.
	const initial = (() => {
		const preferences = loadPreferences();
		const audio = pickAudio(session.audio, preferences);
		return {
			preferences,
			audio,
			subtitles: pickSubtitles(session.subtitles, audio, preferences)
		};
	})();

	let root: HTMLDivElement;
	let video: HTMLVideoElement;
	let cues: HTMLDivElement;
	let engine: Engine | null = null;
	let renderer: SubtitleRenderer | null = null;
	let loadToken = 0;

	let paused = $state(true);
	let currentTime = $state(0);
	let mediaDuration = $state(NaN);
	let buffered = $state<{ start: number; end: number }[]>([]);
	let volume = $state(initial.preferences.volume);
	let muted = $state(initial.preferences.muted);
	let ended = $state(false);
	let waiting = $state(true);
	let started = $state(false);
	let autoplayBlocked = $state(false);
	let fatal = $state<string | null>(null);
	let fullscreen = $state(false);
	let pipSupported = $state(false);
	let controlsVisible = $state(true);
	let menu = $state<'subtitles' | 'audio' | 'versions' | null>(null);
	let audioId = $state(initial.audio?.id ?? null);
	let subtitleId = $state<number | null>(initial.subtitles?.id ?? null);
	let lastSubtitleId: number | null = initial.subtitles?.id ?? null;
	let subtitleStatus = $state<'idle' | 'loading' | 'error'>('idle');
	let assFallback = $state(false);
	let hideTimer: ReturnType<typeof setTimeout> | undefined;
	let trickplay = $state(untrack(() => session.trickplay ?? null));
	let trickplayRetry = $state(0);
	/** When the last new sheet became ready (or polling began). */
	let trickplayProgressAt = Date.now();

	const duration = $derived(
		Number.isFinite(mediaDuration) && mediaDuration > 0 ? mediaDuration : session.duration
	);
	const audioTrack = $derived(session.audio.find((track) => track.id === audioId) ?? null);
	const canSwitchAudio = $derived(session.mode === 'hls' && session.audio.length > 1);
	const ready = $derived(started || autoplayBlocked || fatal !== null);
	const showControls = $derived(
		ready && (controlsVisible || paused || menu !== null || fatal !== null)
	);
	const volumeIcon = $derived<IconName>(
		muted || volume === 0 ? 'volume-off' : volume < 0.5 ? 'volume-low' : 'volume'
	);

	const subtitleOptions = $derived<MenuOption[]>([
		{ id: null, label: 'Off' },
		...session.subtitles.map((track) => ({
			id: track.id,
			label: subtitleName(track),
			detail: [
				track.forced ? 'Forced' : null,
				track.format === 'ass' ? 'Styled' : null,
				track.format === 'pgs' ? 'Picture' : null,
				track.external ? 'Subtitle file' : null
			]
				.filter(Boolean)
				.join(' · '),
			note:
				track.id === subtitleId && subtitleStatus === 'error'
					? "Couldn't load these subtitles"
					: track.id === subtitleId && assFallback
						? 'Shown without styling'
						: undefined
		}))
	]);
	const audioOptions = $derived<MenuOption[]>(
		session.audio.map((track) => ({
			id: track.id,
			label: audioName(track),
			detail: audioDetail(track)
		}))
	);
	const versionOptions = $derived<MenuOption[]>(
		versions.map((version) => ({
			id: version.file_id,
			label: versionName(version),
			detail: versionSize(version),
			disabled: !version.playable,
			note: version.problem ?? undefined
		}))
	);
	const selectedVersion = $derived(versions.find((version) => version.selected)?.file_id ?? null);

	function renderCues(fragments: DocumentFragment[]) {
		// Svelte renders nothing inside this element; cues are browser-parsed WebVTT markup.
		// eslint-disable-next-line svelte/no-dom-manipulating
		cues?.replaceChildren(
			...fragments.map((fragment) => {
				const line = document.createElement('div');
				line.className = 'cue';
				line.append(fragment);
				return line;
			})
		);
	}

	async function load(url: string, at: number, resume: boolean) {
		const token = ++loadToken;
		engine?.destroy();
		engine = null;
		fatal = null;
		waiting = true;
		try {
			const attached = await attach({
				video,
				url,
				mode: session.mode,
				startAt: at,
				onfatal: (message) => {
					if (token === loadToken) fatal = message;
				}
			});
			if (token !== loadToken) {
				attached.destroy();
				return;
			}
			engine = attached;
			if (resume) await play();
		} catch (error) {
			if (token === loadToken) fatal = error instanceof Error ? error.message : String(error);
		}
	}

	async function play() {
		try {
			await video.play();
			autoplayBlocked = false;
		} catch (error) {
			// Browsers refuse to autoplay with sound until the page was interacted with.
			if (error instanceof DOMException && error.name === 'NotAllowedError') autoplayBlocked = true;
		}
	}

	function togglePlay() {
		if (fatal) return;
		if (video.paused || video.ended) void play();
		else video.pause();
	}

	function seek(time: number) {
		video.currentTime = Math.min(Math.max(time, 0), Math.max(duration - 0.5, 0));
	}

	function skip(seconds: number) {
		seek(video.currentTime + seconds);
		wake();
	}

	function setVolume(value: number) {
		video.volume = Math.min(Math.max(value, 0), 1);
		video.muted = video.volume === 0;
	}

	function toggleMute() {
		if (video.muted && video.volume === 0) video.volume = 0.5;
		video.muted = !video.muted;
	}

	async function toggleFullscreen() {
		if (document.fullscreenElement) {
			await document.exitFullscreen();
		} else if (root.requestFullscreen) {
			await root.requestFullscreen().catch(() => {});
		} else {
			// iPhone Safari only lets the video element itself go fullscreen.
			(
				video as HTMLVideoElement & { webkitEnterFullscreen?: () => void }
			).webkitEnterFullscreen?.();
		}
	}

	async function togglePip() {
		if (document.pictureInPictureElement) await document.exitPictureInPicture();
		else await video.requestPictureInPicture().catch(() => {});
	}

	async function selectSubtitles(id: number | null, remember = false) {
		menu = null;
		subtitleId = id;
		if (id !== null) lastSubtitleId = id;
		const track = session.subtitles.find((candidate) => candidate.id === id) ?? null;
		if (remember) savePreferences({ subtitleLanguage: track ? (track.language ?? null) : 'off' });
		subtitleStatus = track ? 'loading' : 'idle';
		assFallback = false;
		try {
			const shown = await renderer?.show(track, session.fonts);
			if (subtitleId !== id) return;
			subtitleStatus = 'idle';
			assFallback = track?.format === 'ass' && shown === 'text';
		} catch {
			if (subtitleId === id) subtitleStatus = 'error';
		}
	}

	function selectAudio(id: number | null) {
		menu = null;
		const track = session.audio.find((candidate) => candidate.id === id);
		if (!track || id === audioId) return;
		audioId = id;
		savePreferences({ audioLanguage: track.language ?? null });
		void load(track.url, video.currentTime, !video.paused);
	}

	function selectVersion(id: number | null) {
		menu = null;
		if (id !== null && id !== selectedVersion) onversion(id, video.currentTime);
	}

	function toggleMenu(name: NonNullable<typeof menu>) {
		menu = menu === name ? null : name;
	}

	/** Shows the controls, and hides them again after a while of not moving. */
	function wake() {
		controlsVisible = true;
		clearTimeout(hideTimer);
		hideTimer = setTimeout(() => {
			if (!video.paused && menu === null) controlsVisible = false;
		}, IDLE_MS);
	}

	let lastPointer = 'mouse';
	function onvideoclick() {
		if (menu) {
			menu = null;
			return;
		}
		// A tap shows or hides the controls; a click plays or pauses.
		if (lastPointer === 'touch') {
			if (showControls && !video.paused) controlsVisible = false;
			else wake();
			return;
		}
		togglePlay();
		wake();
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
		const target = event.target as HTMLElement | null;
		if (event.key === 'Escape' && menu) {
			// Close the menu, not the player.
			menu = null;
			event.stopPropagation();
			return;
		}
		if (target?.closest('input[type="range"]') && event.key.startsWith('Arrow')) return;
		if (target?.closest('button, a') && (event.key === ' ' || event.key === 'Enter')) return;
		switch (event.key) {
			case ' ':
			case 'k':
				togglePlay();
				break;
			case 'ArrowLeft':
			case 'j':
				skip(-SKIP_SECONDS);
				break;
			case 'ArrowRight':
			case 'l':
				skip(SKIP_SECONDS);
				break;
			case 'ArrowUp':
				setVolume(video.volume + 0.1);
				break;
			case 'ArrowDown':
				setVolume(video.volume - 0.1);
				break;
			case 'f':
				void toggleFullscreen();
				break;
			case 'm':
				toggleMute();
				break;
			case 'c':
				void selectSubtitles(
					subtitleId === null ? (lastSubtitleId ?? session.subtitles[0]?.id ?? null) : null,
					true
				);
				break;
			default:
				return;
		}
		event.preventDefault();
		wake();
	}

	function reportProgress(element: HTMLVideoElement | null = video): Promise<void> | void {
		// Before the first frame the position is just where we asked to start.
		if (!started || !onprogress || !element || !(duration > 0)) return;
		return onprogress(element.ended ? duration : element.currentTime, duration);
	}

	/** For events: report without waiting for it to be recorded. */
	function report() {
		void reportProgress();
	}

	/** Reports where playback is now; resolves once that's been recorded. */
	export async function flushProgress(): Promise<void> {
		await reportProgress();
	}

	function updateBuffered() {
		const ranges = video.buffered;
		buffered = Array.from({ length: ranges.length }, (_, index) => ({
			start: ranges.start(index),
			end: ranges.end(index)
		}));
	}

	// Show the controls for a moment once there's something to control.
	$effect(() => {
		if (!ready) return;
		untrack(() => {
			onready?.();
			wake();
		});
	});

	// Thumbnails still being made arrive a sheet at a time: ask for more while
	// they are, saying where the viewer is so the server makes those first.
	// Slower once nothing new has come in for a while.
	$effect(() => {
		if (!trickplay?.generating) return;
		void trickplayRetry;
		const id = session.id;
		const readyBefore = trickplay.ready.filter(Boolean).length;
		const stalled = Date.now() - trickplayProgressAt > TRICKPLAY_STALL_MS;
		let cancelled = false;
		const timer = setTimeout(
			async () => {
				try {
					const { data, error } = await api.GET('/api/playback/{session_id}/trickplay', {
						params: {
							path: { session_id: id },
							query: { position: untrack(() => currentTime) }
						}
					});
					if (cancelled) return;
					if (error) trickplay = trickplay ? { ...trickplay, generating: false } : null;
					else trickplay = data ?? null;
					if ((trickplay?.ready.filter(Boolean).length ?? 0) > readyBefore) {
						trickplayProgressAt = Date.now();
					}
				} catch {
					if (!cancelled) trickplayRetry++;
				}
			},
			stalled ? TRICKPLAY_SLOW_POLL_MS : TRICKPLAY_POLL_MS
		);
		return () => {
			cancelled = true;
			clearTimeout(timer);
		};
	});

	onMount(() => {
		video.volume = volume;
		video.muted = muted;
		pipSupported = document.pictureInPictureEnabled && !!video.requestPictureInPicture;
		renderer = new SubtitleRenderer(video, renderCues);
		void load(initial.audio?.url ?? session.url, startAt, true);
		if (subtitleId !== null) void selectSubtitles(subtitleId);

		const onfullscreen = () => (fullscreen = document.fullscreenElement === root);
		document.addEventListener('fullscreenchange', onfullscreen);
		const progressTimer = setInterval(() => {
			if (!video.paused) report();
		}, PROGRESS_INTERVAL_MS);
		window.addEventListener('pagehide', report);
		if ('mediaSession' in navigator) {
			navigator.mediaSession.metadata = new MediaMetadata({ title, artist: detail ?? '' });
			navigator.mediaSession.setActionHandler('seekbackward', () => skip(-SKIP_SECONDS));
			navigator.mediaSession.setActionHandler('seekforward', () => skip(SKIP_SECONDS));
		}

		// Teardown may unset `video` before this cleanup runs.
		const element = video;
		return () => {
			void reportProgress(element);
			clearInterval(progressTimer);
			window.removeEventListener('pagehide', report);
			loadToken++;
			clearTimeout(hideTimer);
			document.removeEventListener('fullscreenchange', onfullscreen);
			renderer?.destroy();
			engine?.destroy();
			if (document.fullscreenElement === root) void document.exitFullscreen();
			if ('mediaSession' in navigator) {
				navigator.mediaSession.metadata = null;
				navigator.mediaSession.setActionHandler('seekbackward', null);
				navigator.mediaSession.setActionHandler('seekforward', null);
			}
		};
	});
</script>

<svelte:window onkeydowncapture={onkeydown} />

<div
	class="player"
	class:idle={!showControls}
	bind:this={root}
	onpointermove={(event) => {
		lastPointer = event.pointerType;
		if (event.pointerType === 'mouse') wake();
	}}
	onpointerdown={(event) => (lastPointer = event.pointerType)}
	role="region"
	aria-label="Video player"
>
	<video
		bind:this={video}
		bind:paused
		bind:currentTime
		bind:duration={mediaDuration}
		bind:volume
		bind:muted
		bind:ended
		playsinline
		onclick={onvideoclick}
		ondblclick={() => void toggleFullscreen()}
		onwaiting={() => (waiting = true)}
		onseeking={() => (waiting = true)}
		onplaying={() => {
			waiting = false;
			started = true;
		}}
		oncanplay={() => (waiting = false)}
		onprogress={updateBuffered}
		ontimeupdate={updateBuffered}
		onvolumechange={() => savePreferences({ volume: video.volume, muted: video.muted })}
		onpause={() => {
			wake();
			report();
		}}
		onended={report}
	></video>

	<div class="cues" class:raised={showControls} bind:this={cues} aria-hidden="true"></div>

	<div class="center">
		{#if fatal}
			<div class="problem" role="alert">
				<Icon name="alert" size="2rem" />
				<h1>Playback stopped</h1>
				<p>{fatal}</p>
				<div class="actions">
					<Button icon="play" onclick={() => onretry(currentTime || startAt)}>Try again</Button>
					<Button variant="secondary" icon="search" onclick={() => onfallback(fatal ?? '')}>
						Find a release instead
					</Button>
				</div>
			</div>
		{:else if !ready}
			<!-- Starting up: nothing to show yet. -->
		{:else if waiting && !paused}
			<Spinner size="3.5rem" label="Buffering" />
		{:else if paused && (!started || ended || autoplayBlocked)}
			<button
				type="button"
				class="big-play"
				aria-label={ended ? 'Watch again' : 'Play'}
				onclick={() => {
					if (ended) seek(0);
					void play();
				}}
			>
				<Icon name="play" size="2.25rem" />
			</button>
		{/if}
	</div>

	<header class="chrome top" class:shown={showControls}>
		<IconButton icon="arrow-left" label="Back (Esc)" size="lg" onclick={onclose} />
		<div class="title">
			<h2>{title}</h2>
			{#if detail}<span>{detail}</span>{/if}
		</div>
	</header>

	<div class="chrome bottom" class:shown={showControls}>
		{#if menu}
			<div class="menu-anchor">
				{#if menu === 'subtitles'}
					<PlayerMenu
						title="Subtitles"
						options={subtitleOptions}
						selected={subtitleId}
						loading={subtitleStatus === 'loading'}
						onselect={(id: number | null) => void selectSubtitles(id, true)}
					/>
				{:else if menu === 'audio'}
					<PlayerMenu
						title="Audio"
						options={audioOptions}
						selected={audioId}
						onselect={selectAudio}
					/>
				{:else}
					<PlayerMenu
						title="Version"
						options={versionOptions}
						selected={selectedVersion}
						onselect={selectVersion}
					/>
				{/if}
			</div>
		{/if}

		<SeekBar {currentTime} {duration} {buffered} {trickplay} onseek={seek} />

		<div class="bar">
			<button
				type="button"
				class="control filled"
				aria-label={paused ? 'Play (k)' : 'Pause (k)'}
				title={paused ? 'Play (k)' : 'Pause (k)'}
				onclick={togglePlay}
			>
				<Icon name={paused ? 'play' : 'pause'} />
			</button>
			<button
				type="button"
				class="control"
				aria-label="Back {SKIP_SECONDS} seconds (←)"
				title="Back {SKIP_SECONDS} seconds (←)"
				onclick={() => skip(-SKIP_SECONDS)}
			>
				<Icon name="skip-back" />
			</button>
			<button
				type="button"
				class="control"
				aria-label="Forward {SKIP_SECONDS} seconds (→)"
				title="Forward {SKIP_SECONDS} seconds (→)"
				onclick={() => skip(SKIP_SECONDS)}
			>
				<Icon name="skip-forward" />
			</button>
			<div class="volume">
				<button
					type="button"
					class="control"
					aria-label={muted ? 'Unmute (m)' : 'Mute (m)'}
					title={muted ? 'Unmute (m)' : 'Mute (m)'}
					onclick={toggleMute}
				>
					<Icon name={volumeIcon} />
				</button>
				<input
					type="range"
					min="0"
					max="1"
					step="0.05"
					value={muted ? 0 : volume}
					aria-label="Volume"
					style:--level="{(muted ? 0 : volume) * 100}%"
					oninput={(event) => setVolume(Number(event.currentTarget.value))}
				/>
			</div>
			<span class="time">
				{formatTime(currentTime)} <span class="total">/ {formatTime(duration)}</span>
			</span>

			<span class="spacer"></span>

			{#if session.subtitles.length}
				<button
					type="button"
					class="control"
					class:on={subtitleId !== null}
					aria-label="Subtitles (c)"
					title="Subtitles (c)"
					aria-expanded={menu === 'subtitles'}
					onclick={() => toggleMenu('subtitles')}
				>
					<Icon name="captions" />
				</button>
			{/if}
			{#if canSwitchAudio}
				<button
					type="button"
					class="control labelled"
					aria-label="Audio: {audioTrack ? audioName(audioTrack) : ''}"
					title="Audio"
					aria-expanded={menu === 'audio'}
					onclick={() => toggleMenu('audio')}
				>
					<Icon name="audio-lines" />
					<span class="hint">{audioTrack?.language?.toUpperCase() ?? ''}</span>
				</button>
			{/if}
			{#if versions.length > 1}
				<button
					type="button"
					class="control"
					aria-label="Version"
					title="Version"
					aria-expanded={menu === 'versions'}
					onclick={() => toggleMenu('versions')}
				>
					<Icon name="layers" />
				</button>
			{/if}
			{#if pipSupported}
				<button
					type="button"
					class="control optional"
					aria-label="Picture in picture"
					title="Picture in picture"
					onclick={() => void togglePip()}
				>
					<Icon name="pip" />
				</button>
			{/if}
			<button
				type="button"
				class="control"
				aria-label={fullscreen ? 'Exit full screen (f)' : 'Full screen (f)'}
				title={fullscreen ? 'Exit full screen (f)' : 'Full screen (f)'}
				onclick={() => void toggleFullscreen()}
			>
				<Icon name={fullscreen ? 'minimize' : 'maximize'} />
			</button>
		</div>
	</div>
</div>

<style>
	.player {
		position: fixed;
		inset: 0;
		z-index: 1;
		container-type: size;
		background: #000;
		color: #fff;
		overflow: hidden;
	}

	.player.idle {
		cursor: none;
	}

	video {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: contain;
		background: #000;
	}

	/* JASSUB draws ASS subtitles on a canvas it puts next to the video. */
	.player :global(canvas) {
		pointer-events: none;
	}

	.cues {
		position: absolute;
		inset: auto var(--page-gutter) 6cqh;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.15em;
		font-size: clamp(1rem, min(4.2cqh, 3.4cqw), 2.75rem);
		line-height: 1.25;
		text-align: center;
		pointer-events: none;
		transition: bottom var(--duration-slow) var(--ease-out);
	}

	.cues.raised {
		bottom: max(6cqh, 7.5rem);
	}

	.cues :global(.cue) {
		max-width: min(90%, 60rem);
		padding: 0.05em 0.4em;
		border-radius: 0.2em;
		background: oklch(0% 0 0 / 0.55);
		text-shadow: 0 0 0.15em #000;
		white-space: pre-line;
		box-decoration-break: clone;
		-webkit-box-decoration-break: clone;
	}

	.center {
		position: absolute;
		inset: 0;
		z-index: 2;
		display: grid;
		place-items: center;
		pointer-events: none;
	}

	.center > :global(*) {
		pointer-events: auto;
	}

	.center :global(.spinner) {
		pointer-events: none;
		border-color: oklch(100% 0 0 / 0.2);
		border-top-color: #fff;
	}

	.big-play {
		display: grid;
		place-items: center;
		width: 5.5rem;
		height: 5.5rem;
		padding-left: 0.3rem;
		border: none;
		border-radius: var(--radius-full);
		background: oklch(from var(--color-accent) l c h / 0.9);
		color: var(--color-accent-contrast);
		cursor: pointer;
		box-shadow: var(--shadow-lg);
		transition: transform var(--duration-fast) var(--ease-out);
	}

	.big-play :global(svg) {
		fill: currentColor;
	}

	.big-play:hover {
		transform: scale(1.06);
	}

	.problem {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		max-width: 32rem;
		margin: var(--page-gutter);
		padding: var(--space-8);
		border-radius: var(--radius-lg);
		background: oklch(from var(--color-surface) l c h / 0.92);
		color: var(--color-text-muted);
		text-align: center;
	}

	.problem :global(svg) {
		color: var(--color-danger);
	}

	.problem h1 {
		font-family: var(--font-display);
		font-size: var(--text-xl);
		color: var(--color-text);
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: var(--space-3);
		margin-top: var(--space-2);
	}

	.chrome {
		position: absolute;
		inset-inline: 0;
		z-index: 3;
		padding-inline: var(--page-gutter);
		opacity: 0;
		pointer-events: none;
		transition: opacity var(--duration-slow) var(--ease-out);
	}

	.chrome.shown {
		opacity: 1;
		pointer-events: auto;
	}

	.top {
		top: 0;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding-block: var(--space-4) var(--space-12);
		background: linear-gradient(to bottom, oklch(0% 0 0 / 0.7), transparent);
	}

	.title {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		min-width: 0;
		white-space: nowrap;
	}

	.title h2 {
		overflow: hidden;
		text-overflow: ellipsis;
		font-family: var(--font-display);
		font-size: var(--text-lg);
		font-weight: 600;
	}

	.title span {
		color: oklch(100% 0 0 / 0.7);
	}

	.top :global(.icon-button) {
		flex-shrink: 0;
		border-color: oklch(100% 0 0 / 0.15);
		background: oklch(0% 0 0 / 0.35);
		color: #fff;
	}

	.bottom {
		bottom: 0;
		padding-block: var(--space-12) var(--space-3);
		background: linear-gradient(to top, oklch(0% 0 0 / 0.75), transparent);
	}

	.menu-anchor {
		position: absolute;
		right: var(--page-gutter);
		bottom: calc(100% - var(--space-8));
	}

	.bar {
		display: flex;
		align-items: center;
		gap: var(--space-1);
	}

	.control {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		min-width: 2.75rem;
		height: 2.75rem;
		padding: 0 var(--space-2);
		border: none;
		border-radius: var(--radius-full);
		background: none;
		color: oklch(100% 0 0 / 0.85);
		font-size: 1.35rem;
		cursor: pointer;
		transition:
			background var(--duration-fast),
			color var(--duration-fast);
	}

	.control:hover,
	.control[aria-expanded='true'] {
		background: oklch(100% 0 0 / 0.12);
		color: #fff;
	}

	.control.on {
		color: var(--color-accent-strong);
	}

	.filled :global(svg) {
		fill: currentColor;
	}

	.hint {
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.04em;
	}

	.volume {
		display: flex;
		align-items: center;
	}

	.volume input {
		width: 0;
		height: 0.25rem;
		margin: 0;
		opacity: 0;
		appearance: none;
		border-radius: var(--radius-full);
		background: linear-gradient(to right, #fff var(--level), oklch(100% 0 0 / 0.25) var(--level));
		cursor: pointer;
		transition:
			width var(--duration-slow) var(--ease-out),
			opacity var(--duration-fast);
	}

	.volume:hover input,
	.volume:focus-within input {
		width: 5rem;
		margin-inline: var(--space-1) var(--space-2);
		opacity: 1;
	}

	.volume input::-webkit-slider-thumb {
		appearance: none;
		width: 0.75rem;
		height: 0.75rem;
		border-radius: var(--radius-full);
		background: #fff;
	}

	.volume input::-moz-range-thumb {
		width: 0.75rem;
		height: 0.75rem;
		border: none;
		border-radius: var(--radius-full);
		background: #fff;
	}

	.time {
		margin-left: var(--space-2);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.total {
		color: oklch(100% 0 0 / 0.6);
	}

	.spacer {
		flex: 1;
	}

	@media (max-width: 40rem) {
		.optional,
		.volume input {
			display: none;
		}

		.control {
			min-width: 2.5rem;
			padding: 0 var(--space-1);
		}

		.total {
			display: none;
		}
	}

	@media (hover: none) {
		.volume input {
			display: none;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.chrome,
		.cues {
			transition: none;
		}
	}
</style>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { untrack } from 'svelte';
	import { fade } from 'svelte/transition';
	import {
		api,
		type DownloadStatus,
		type PlaybackOffer,
		type RankedRelease,
		type Rejected,
		type WatchPlan
	} from '#lib/api/client.ts';
	import DownloadProgress from '#lib/components/watch/DownloadProgress.svelte';
	import PlaybackCurtain from '#lib/components/watch/player/PlaybackCurtain.svelte';
	import Player from '#lib/components/watch/player/Player.svelte';
	import SelectedRelease from '#lib/components/watch/SelectedRelease.svelte';
	import UpgradeOptions from '#lib/components/watch/UpgradeOptions.svelte';
	import WatchLoading from '#lib/components/watch/WatchLoading.svelte';
	import WatchStage from '#lib/components/watch/WatchStage.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Icon from '#lib/components/ui/Icon.svelte';
	import InlineAlert from '#lib/components/ui/InlineAlert.svelte';
	import StatusMessage from '#lib/components/ui/StatusMessage.svelte';
	import { mediaHref } from '#lib/media/format.ts';
	import { detectCapabilities } from '#lib/playback/capabilities.ts';
	import { saveProgress } from '#lib/progress/progress.ts';
	import { episodeCode, languageName } from '#lib/watch/labels.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const media = $derived(data.media);
	const episodeLabel = $derived(
		data.episode ? episodeCode(data.episode.season, data.episode.episode) : null
	);
	/** The library has a copy of this title (or episode); whether it plays is the server's call. */
	const inLibrary = $derived(
		(data.availability?.files ?? []).some(
			(file) =>
				!data.episode ||
				file.episodes.some(
					(episode) =>
						episode.season === data.episode?.season && episode.episode === data.episode?.episode
				)
		)
	);

	/**
	 * Library playback first; otherwise a download in progress (`checking` looks for one), and
	 * the release search when there's neither.
	 */
	let phase = $state<'checking' | 'downloading' | 'starting' | 'playing' | 'search'>(
		untrack(() => inLibrary) ? 'starting' : 'checking'
	);
	/** The player has its first frame up; until then a curtain covers it. */
	let playerReady = $state(false);
	let curtainMessage = $state('Starting playback');
	let offer = $state<PlaybackOffer | null>(null);
	let startAt = $state(0);
	/** Why the library copy isn't playing, shown above the release search. */
	let notice = $state<{ message: string; retry: boolean } | null>(null);
	let startToken = 0;
	let player = $state<{ flushProgress: () => Promise<void> } | null>(null);

	let status = $state<'loading' | 'ready' | 'error'>('loading');
	let plan = $state<WatchPlan | null>(null);
	let errorMessage = $state('');
	/** An upgrade the user picked instead of the recommendation. */
	let chosen = $state<RankedRelease | null>(null);
	let attempt = $state(0);

	let download = $state<DownloadStatus | null>(null);
	/** The pick is being handed to qBittorrent. */
	let startingDownload = $state(false);
	let cancelling = $state(false);
	let downloadError = $state<string | null>(null);

	const shown = $derived(chosen ?? plan?.pick ?? null);
	const others = $derived(plan?.options ?? []);
	/** "9 not the requested episode, 1 too few seeders" */
	const rejectedSummary = $derived(
		(plan?.rejected ?? []).map((r: Rejected) => `${r.count} ${r.reason}`).join(', ')
	);
	const sessionId = $derived(offer?.session?.id ?? null);
	const selectedFile = $derived(offer?.versions.find((version) => version.selected)?.file_id);

	function errorDetail(error: unknown): string | null {
		const detail = (error as { detail?: unknown } | undefined)?.detail;
		return typeof detail === 'string' ? detail : null;
	}

	function search(message: string | null, retry = false) {
		startToken++;
		offer = null;
		download = null;
		notice = message ? { message, retry } : null;
		phase = 'search';
	}

	async function startLocal(fileId: number | null = null, at = 0, message = 'Starting playback') {
		const token = ++startToken;
		phase = 'starting';
		playerReady = false;
		curtainMessage = message;
		notice = null;
		startAt = at;
		try {
			const {
				data: result,
				error,
				response
			} = await api.POST('/api/playback', {
				body: {
					media_type: media.media_type,
					media_id: media.id,
					season: data.episode?.season ?? null,
					episode: data.episode?.episode ?? null,
					file_id: fileId,
					capabilities: detectCapabilities()
				}
			});
			if (token !== startToken) return;
			if (result?.session) {
				offer = result;
				phase = 'playing';
			} else if (result) {
				search(`Your library copy can't play in this browser. ${result.problem ?? ''}`, false);
			} else {
				const detail = errorDetail(error) ?? `HTTP ${response.status}`;
				search(`Couldn't start your library copy: ${detail}`, response.status >= 500);
			}
		} catch (err) {
			if (token !== startToken) return;
			const detail = err instanceof Error ? err.message : String(err);
			search(`Couldn't start your library copy: ${detail}`, true);
		}
	}

	/** Pick up a download that's still running for this title, or search for releases. */
	async function resumeOrSearch() {
		const token = ++startToken;
		offer = null;
		notice = null;
		download = null;
		downloadError = null;
		phase = 'checking';
		try {
			const { data: active } = await api.GET('/api/downloads', {
				params: {
					query: {
						media_type: media.media_type,
						media_id: media.id,
						season: data.episode?.season ?? null,
						episode: data.episode?.episode ?? null
					}
				}
			});
			if (token !== startToken) return;
			if (active) {
				download = active;
				phase = 'downloading';
				return;
			}
		} catch {
			if (token !== startToken) return;
		}
		phase = 'search';
	}

	// A new title or episode: play it from the library if it's there, where the user left off.
	$effect(() => {
		void [media.media_type, media.id, data.episode?.season, data.episode?.episode];
		const local = inLibrary;
		untrack(() => {
			if (local) {
				void startLocal(null, data.resumeAt, data.resumeAt ? 'Resuming' : 'Starting playback');
			} else {
				void resumeOrSearch();
			}
		});
	});

	/** Hand a release to qBittorrent and follow it; false (with `downloadError` set) on failure. */
	async function startDownload(ranked: RankedRelease): Promise<boolean> {
		startingDownload = true;
		downloadError = null;
		try {
			const {
				data: started,
				error,
				response
			} = await api.POST('/api/downloads', {
				body: {
					media_type: media.media_type,
					media_id: media.id,
					season: data.episode?.season ?? null,
					episode: data.episode?.episode ?? null,
					indexer: ranked.release.indexer,
					guid: ranked.release.guid
				}
			});
			if (started) {
				startToken++;
				download = started;
				notice = null;
				phase = 'downloading';
				return true;
			}
			downloadError = `Couldn't start the download: ${errorDetail(error) ?? `HTTP ${response.status}`}`;
		} catch (err) {
			downloadError = `Couldn't start the download: ${err instanceof Error ? err.message : String(err)}`;
		} finally {
			startingDownload = false;
		}
		return false;
	}

	async function cancelDownload() {
		if (!download) return;
		cancelling = true;
		try {
			const {
				data: result,
				error,
				response
			} = await api.DELETE('/api/downloads/{download_id}', {
				params: { path: { download_id: download.id } }
			});
			if (result) {
				void close();
			} else {
				downloadError = `Couldn't cancel: ${errorDetail(error) ?? `HTTP ${response.status}`}`;
			}
		} catch (err) {
			downloadError = `Couldn't cancel: ${err instanceof Error ? err.message : String(err)}`;
		} finally {
			cancelling = false;
		}
	}

	// Follow the download; once it's in the library, play it.
	const downloadId = $derived(phase === 'downloading' ? (download?.id ?? null) : null);
	$effect(() => {
		const id = downloadId;
		if (id == null) return;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const poll = async () => {
			try {
				const { data: latest } = await api.GET('/api/downloads/{download_id}', {
					params: { path: { download_id: id } }
				});
				if (stopped) return;
				if (latest) {
					download = latest;
					if (latest.state === 'completed' && latest.file_id != null) {
						void startLocal(latest.file_id, 0, 'Starting playback');
						return;
					}
					if (latest.state === 'failed' || latest.state === 'cancelled') return;
				}
			} catch {
				if (stopped) return;
			}
			timer = setTimeout(() => void poll(), 1000);
		};
		timer = setTimeout(() => void poll(), 1000);
		return () => {
			stopped = true;
			clearTimeout(timer);
		};
	});

	// Stop the server's work when the session is replaced, the page is left, or the tab closes.
	$effect(() => {
		const id = sessionId;
		if (!id) return;
		const stop = () =>
			void api.DELETE('/api/playback/{session_id}', {
				params: { path: { session_id: id } },
				keepalive: true
			});
		window.addEventListener('pagehide', stop);
		return () => {
			window.removeEventListener('pagehide', stop);
			stop();
		};
	});

	$effect(() => {
		if (phase !== 'search') return;
		const controller = new AbortController();
		const { media_type, id } = media;
		const episode = data.episode;
		void attempt; // re-run on retry

		status = 'loading';
		chosen = null;
		api
			.GET('/api/media/{media_type}/{media_id}/watch', {
				params: { path: { media_type, media_id: id }, query: episode ?? {} },
				signal: controller.signal
			})
			.then(async ({ data: result, response }) => {
				if (result) {
					plan = result;
					// Grab the pick straight away, still under "Checking for torrents"; the release
					// card only shows when that can't happen (or fails).
					if (result.pick && result.can_download) {
						const started = await startDownload(result.pick);
						if (started || controller.signal.aborted) return;
					}
					status = 'ready';
				} else {
					errorMessage = `The search failed (HTTP ${response.status}).`;
					status = 'error';
				}
			})
			.catch((err: unknown) => {
				if (controller.signal.aborted) return;
				errorMessage = err instanceof Error ? err.message : String(err);
				status = 'error';
			});
		return () => controller.abort();
	});

	/** Each step of finding something to watch fades in, rather than popping in. */
	const VIEW_FADE = { duration: 250 };

	function choose(option: RankedRelease) {
		chosen = option;
	}

	function recordProgress(position: number, duration: number): Promise<void> {
		return saveProgress(media, data.episode, position, duration);
	}

	async function close() {
		// Record where playback stopped before leaving, so the next page sees it.
		const flushed = player?.flushProgress();
		if (flushed) await Promise.race([flushed, new Promise((done) => setTimeout(done, 1500))]);
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- mediaHref resolves
		void goto(mediaHref(media.media_type, media.id));
	}
</script>

<svelte:head>
	<title>Watch {media.title}{episodeLabel ? ` ${episodeLabel}` : ''} · Driftwood</title>
</svelte:head>

{#snippet downloadErrorText()}{download?.error}{/snippet}

<WatchStage
	title={media.title}
	year={media.year}
	detail={episodeLabel}
	backdropPath={media.backdrop_path}
	immersive={phase === 'starting' || phase === 'playing'}
	onclose={() => void close()}
>
	{#if phase === 'checking'}
		<!-- Looking for a download in progress: a moment, so nothing to show. -->
	{:else if phase === 'downloading' && download}
		{#if download.state === 'failed' || download.state === 'cancelled'}
			<div class="view" in:fade={VIEW_FADE}>
				<StatusMessage
					icon="alert"
					tone={download.state === 'failed' ? 'danger' : 'neutral'}
					title={download.state === 'failed' ? "The download didn't finish" : 'Download cancelled'}
					children={download.error ? downloadErrorText : undefined}
				>
					{#snippet actions()}
						<Button onclick={() => search(null)}>Try again</Button>
					{/snippet}
				</StatusMessage>
			</div>
		{:else}
			<div class="view" in:fade={VIEW_FADE}>
				{#key download.id}
					<DownloadProgress {download} {cancelling} oncancel={() => void cancelDownload()} />
				{/key}
				{#if downloadError}
					<InlineAlert>{downloadError}</InlineAlert>
				{/if}
			</div>
		{/if}
	{:else if phase !== 'search'}
		{#if phase === 'playing' && offer?.session}
			{#key offer.session.id}
				<Player
					bind:this={player}
					session={offer.session}
					versions={offer.versions}
					title={media.title}
					detail={episodeLabel}
					{startAt}
					onclose={() => void close()}
					onversion={(fileId: number, at: number) =>
						void startLocal(fileId, at, 'Switching version')}
					onretry={(at: number) => void startLocal(selectedFile ?? null, at)}
					onfallback={(reason: string) =>
						search(`Playback of your library copy stopped. ${reason}`, true)}
					onready={() => (playerReady = true)}
					onprogress={recordProgress}
				/>
			{/key}
		{/if}
		<PlaybackCurtain
			title={media.title}
			detail={episodeLabel}
			backdropPath={media.backdrop_path}
			message={curtainMessage}
			lifted={playerReady}
			onclose={() => void close()}
		/>
	{:else}
		{#key status}
			<div class="view" in:fade={VIEW_FADE}>
				{#if notice}
					<div class="notice" role="status">
						<Icon name="info" size="1.25rem" />
						<p>{notice.message}</p>
						{#if notice.retry}
							<Button variant="secondary" icon="play" onclick={() => void startLocal()}>
								Try the library copy
							</Button>
						{/if}
					</div>
				{/if}
				{#if status === 'loading'}
					<WatchLoading title={media.title} detail={episodeLabel} />
				{:else if status === 'error'}
					<StatusMessage
						icon="alert"
						tone="danger"
						title="Couldn't check for torrents"
						role="alert"
					>
						{errorMessage}
						{#snippet actions()}
							<Button onclick={() => attempt++}>Try again</Button>
						{/snippet}
					</StatusMessage>
				{:else if plan}
					{#if shown}
						<SelectedRelease
							ranked={shown}
							isRecommended={!chosen || chosen.release.guid === plan.pick?.release.guid}
							wantedSubtitles={plan.subtitle_languages}
							canDownload={plan.can_download}
							starting={startingDownload}
							ondownload={() => shown && void startDownload(shown)}
							onreset={() => (chosen = null)}
						/>
						{#if downloadError}
							<InlineAlert>{downloadError}</InlineAlert>
						{/if}
					{:else}
						<StatusMessage icon="info" title="Nothing good to watch yet">
							{#if !plan.indexers.length}
								No indexers are configured. Set <code>
									DRIFTWOOD_INDEXERS__TORRENTLEECH__USERNAME
								</code>
								and <code>__PASSWORD</code> in the backend's <code>.env</code>.
							{:else if plan.considered}
								The indexers found {plan.considered} release{plan.considered === 1 ? '' : 's'}, but
								none is good to watch{#if rejectedSummary}&nbsp;({rejectedSummary}){/if}.
							{:else}
								The indexers didn't find any releases for this title.
							{/if}
							{#snippet actions()}
								<Button variant="secondary" onclick={() => attempt++}>Search again</Button>
							{/snippet}
						</StatusMessage>
					{/if}

					{#each plan.failures as failure (failure.indexer + failure.message)}
						<InlineAlert>{failure.indexer}: {failure.message}</InlineAlert>
					{/each}

					{#if others.length > 1 || (others.length === 1 && !plan.pick)}
						<UpgradeOptions
							options={others}
							selectedGuid={shown?.release.guid ?? null}
							onselect={choose}
						/>
					{/if}

					<details class="search-details">
						<summary>Search details</summary>
						<dl>
							<dt>Query</dt>
							<dd><code>{plan.query}</code></dd>
							<dt>Indexers</dt>
							<dd>{plan.indexers.join(', ') || 'none'}</dd>
							<dt>Releases found</dt>
							<dd>{plan.considered}</dd>
							<dt>Wanted subtitles</dt>
							<dd>{plan.subtitle_languages.map(languageName).join(', ') || 'any (checks off)'}</dd>
							<dt>NFOs checked</dt>
							<dd>{plan.nfos_checked}</dd>
							{#each plan.rejected as rejection (rejection.reason)}
								<dt>Skipped: {rejection.reason}</dt>
								<dd>{rejection.count}</dd>
							{/each}
						</dl>
					</details>
				{/if}
			</div>
		{/key}
	{/if}
</WatchStage>

<style>
	/* Lays its children out like the stage's content column it stands in for. */
	.view {
		display: flex;
		flex-direction: column;
		gap: var(--space-8);
	}

	.notice {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}

	.notice p {
		flex: 1 1 16rem;
	}

	.notice :global(svg) {
		flex-shrink: 0;
		color: var(--color-accent);
	}

	code {
		font-size: var(--text-xs);
		color: var(--color-text);
		overflow-wrap: anywhere;
	}

	.search-details {
		font-size: var(--text-sm);
		color: var(--color-text-faint);
	}

	.search-details summary {
		cursor: pointer;
	}

	.search-details dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-1) var(--space-4);
		margin: var(--space-3) 0 0;
	}

	.search-details dd {
		margin: 0;
		color: var(--color-text-muted);
	}
</style>

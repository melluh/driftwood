<script lang="ts">
	import { goto } from '$app/navigation';
	import { untrack } from 'svelte';
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
	import { mediaHref } from '#lib/media/format.ts';
	import { detectCapabilities } from '#lib/playback/capabilities.ts';
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

	// A new title or episode: play it from the library if it's there.
	$effect(() => {
		void [media.media_type, media.id, data.episode?.season, data.episode?.episode];
		const local = inLibrary;
		untrack(() => {
			if (local) {
				void startLocal();
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
				close();
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

	function choose(option: RankedRelease) {
		chosen = option;
	}

	function close() {
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- mediaHref resolves
		void goto(mediaHref(media.media_type, media.id));
	}
</script>

<svelte:head>
	<title>Watch {media.title}{episodeLabel ? ` ${episodeLabel}` : ''} · Driftwood</title>
</svelte:head>

<WatchStage
	title={media.title}
	year={media.year}
	detail={episodeLabel}
	backdropPath={media.backdrop_path}
	immersive={phase === 'starting' || phase === 'playing'}
	onclose={close}
>
	{#if phase === 'checking'}
		<!-- Looking for a download in progress: a moment, so nothing to show. -->
	{:else if phase === 'downloading' && download}
		{#if download.state === 'failed' || download.state === 'cancelled'}
			<div class="message">
				<Icon name="alert" size="2rem" />
				<h1>
					{download.state === 'failed' ? "The download didn't finish" : 'Download cancelled'}
				</h1>
				{#if download.error}<p>{download.error}</p>{/if}
				<Button onclick={() => search(null)}>Try again</Button>
			</div>
		{:else}
			{#key download.id}
				<DownloadProgress {download} {cancelling} oncancel={() => void cancelDownload()} />
			{/key}
			{#if downloadError}
				<p class="failure"><Icon name="alert" /> {downloadError}</p>
			{/if}
		{/if}
	{:else if phase !== 'search'}
		{#if phase === 'playing' && offer?.session}
			{#key offer.session.id}
				<Player
					session={offer.session}
					versions={offer.versions}
					title={media.title}
					detail={episodeLabel}
					{startAt}
					onclose={close}
					onversion={(fileId: number, at: number) =>
						void startLocal(fileId, at, 'Switching version')}
					onretry={(at: number) => void startLocal(selectedFile ?? null, at)}
					onfallback={(reason: string) =>
						search(`Playback of your library copy stopped. ${reason}`, true)}
					onready={() => (playerReady = true)}
				/>
			{/key}
		{/if}
		<PlaybackCurtain
			title={media.title}
			detail={episodeLabel}
			backdropPath={media.backdrop_path}
			message={curtainMessage}
			lifted={playerReady}
			onclose={close}
		/>
	{:else}
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
			<div class="message">
				<Icon name="alert" size="2rem" />
				<h1>Couldn't check for torrents</h1>
				<p>{errorMessage}</p>
				<Button onclick={() => attempt++}>Try again</Button>
			</div>
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
					<p class="failure"><Icon name="alert" /> {downloadError}</p>
				{/if}
			{:else}
				<div class="message">
					<Icon name="info" size="2rem" />
					<h1>Nothing good to watch yet</h1>
					<p>
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
					</p>
					<Button variant="secondary" onclick={() => attempt++}>Search again</Button>
				</div>
			{/if}

			{#each plan.failures as failure (failure.indexer + failure.message)}
				<p class="failure"><Icon name="alert" /> {failure.indexer}: {failure.message}</p>
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
	{/if}
</WatchStage>

<style>
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

	.message {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		text-align: center;
		color: var(--color-text-muted);
	}

	.message h1 {
		font-family: var(--font-display);
		font-size: var(--text-xl);
		color: var(--color-text);
	}

	.message p {
		max-width: 32rem;
		margin-bottom: var(--space-2);
	}

	.failure {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-danger);
		overflow-wrap: anywhere;
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

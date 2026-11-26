import { api, type ContinueWatching, type MediaType, type WatchProgress } from '#lib/api/client.ts';
import { watchHref } from '#lib/media/format.ts';

type MediaKey = { media_type: MediaType; id: number };
export type EpisodeKey = { season: number; episode: number };

const RESUME_REWIND_SECONDS = 5;

function path(media: MediaKey) {
	return { path: { media_type: media.media_type, media_id: media.id } };
}

/** "Continue watching", most recent first; empty when it can't be loaded. */
export async function loadContinueWatching(
	fetch: typeof globalThis.fetch
): Promise<ContinueWatching[]> {
	const { data } = await api.GET('/api/progress/continue', { fetch }).catch(() => ({ data: null }));
	return data ?? [];
}

/** Where to start a movie or episode: the saved spot while part-way through, else 0. */
export async function loadResumeAt(
	media: MediaKey,
	episode: EpisodeKey | null,
	fetch: typeof globalThis.fetch
): Promise<number> {
	const { data } = await api
		.GET('/api/progress/{media_type}/{media_id}', { params: path(media), fetch })
		.catch(() => ({ data: null }));
	const saved = (data ?? []).find(
		(progress: WatchProgress) =>
			progress.season === (episode?.season ?? null) &&
			progress.episode === (episode?.episode ?? null)
	);
	// Back up a few seconds, to pick the thread up again.
	return saved?.resume_at ? Math.max(0, saved.resume_at - RESUME_REWIND_SECONDS) : 0;
}

/** Records the playback position. Survives the page going away (keepalive); never throws. */
export async function saveProgress(
	media: MediaKey,
	episode: EpisodeKey | null,
	position: number,
	duration: number
): Promise<void> {
	if (!(duration > 0) || !Number.isFinite(position)) return;
	await api
		.PUT('/api/progress/{media_type}/{media_id}', {
			params: path(media),
			body: {
				season: episode?.season ?? null,
				episode: episode?.episode ?? null,
				position: Math.max(0, position),
				duration
			},
			keepalive: true
		})
		.catch(() => {});
}

/** The watch page for a continue-watching entry, at its episode. */
export function continueHref(item: ContinueWatching): string {
	const href = watchHref(item.media.media_type, item.media.id);
	return item.season != null && item.episode != null
		? `${href}?season=${item.season}&episode=${item.episode}`
		: href;
}

/** How far through, 0–1; 0 when unknown. */
export function progressFraction(item: { position: number; duration?: number | null }): number {
	return item.duration ? Math.min(Math.max(item.position / item.duration, 0), 1) : 0;
}

/** "42m left", "1h 5m left"; null when there's nothing to resume. */
export function timeLeft(item: { position: number; duration?: number | null }): string | null {
	if (!item.duration || item.position <= 0) return null;
	const minutes = Math.max(1, Math.round((item.duration - item.position) / 60));
	const hours = Math.floor(minutes / 60);
	return hours ? `${hours}h ${minutes % 60}m left` : `${minutes}m left`;
}

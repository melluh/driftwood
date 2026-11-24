import type { LibraryAvailability, MediaDetails, MediaType } from '#lib/api/client.ts';
import { api } from '#lib/api/client.ts';

type MediaKey = { media_type: MediaType; id: number };

/** What's on disk for a title, or null when that couldn't be checked. */
export async function loadAvailability(
	media: MediaKey,
	fetch: typeof globalThis.fetch
): Promise<LibraryAvailability | null> {
	const { data } = await api.GET('/api/library/{media_type}/{media_id}', {
		params: { path: { media_type: media.media_type, media_id: media.id } },
		fetch
	});
	return data ?? null;
}

/** Label for the ready-to-play badge, or null when this title is not available. */
export function readyLabel(
	media: Pick<MediaDetails, 'media_type' | 'number_of_episodes'>,
	availability: LibraryAvailability | null
): string | null {
	if (!availability?.ready) return null;

	if (media.media_type === 'movie') {
		const file = availability.files[0];
		if (!file) return 'Ready to play';
		const resolution = file.resolution ? ` · ${file.resolution}` : '';
		const hdr = file.hdr_flags.length ? ' HDR' : '';
		return `Ready to play${resolution}${hdr}`;
	}

	const episodes = availability.episodes.filter((episode) => episode.season >= 1).length;
	const total = media.number_of_episodes;
	if (total == null) return `Ready to play · ${episodes} episodes`;
	if (episodes >= total) return 'Ready to play · All episodes';
	return `Ready to play · ${episodes} of ${total} episodes`;
}

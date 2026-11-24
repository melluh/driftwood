import { api, type MediaSummary, type MediaType } from '#lib/api/client.ts';

type MediaKey = { media_type: MediaType; id: number };

function path(media: MediaKey) {
	return { params: { path: { media_type: media.media_type, media_id: media.id } } };
}

/** The signed-in user's saved titles, newest first; empty when the list can't be loaded. */
export async function loadMyList(fetch: typeof globalThis.fetch): Promise<MediaSummary[]> {
	const { data } = await api.GET('/api/my-list', { fetch });
	return data ?? [];
}

/** Whether a title is on the list, or null when that couldn't be checked. */
export async function loadInMyList(
	media: MediaKey,
	fetch: typeof globalThis.fetch
): Promise<boolean | null> {
	const { data } = await api.GET('/api/my-list/{media_type}/{media_id}', { ...path(media), fetch });
	return data?.in_list ?? null;
}

/** Adds or removes a title; resolves to whether the server accepted the change. */
export async function setInMyList(media: MediaKey, inList: boolean): Promise<boolean> {
	const { data } = inList
		? await api.PUT('/api/my-list/{media_type}/{media_id}', path(media))
		: await api.DELETE('/api/my-list/{media_type}/{media_id}', path(media));
	return data?.in_list === inList;
}

export function isSameMedia(a: MediaKey, b: MediaKey): boolean {
	return a.media_type === b.media_type && a.id === b.id;
}

/** `items` with `media` added at the front, or removed. */
export function withMedia(
	items: MediaSummary[],
	media: MediaSummary,
	inList: boolean
): MediaSummary[] {
	const rest = items.filter((item) => !isSameMedia(item, media));
	return inList ? [media, ...rest] : rest;
}

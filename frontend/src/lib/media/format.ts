export { isMediaType, mediaTypeLabel } from './media-type.ts';
import { resolve } from '$app/paths';
import type { MediaType } from '#lib/api/client.ts';

export function mediaHref(type: MediaType, id: number): string {
	return resolve('/[type=mediatype]/[id=tmdbid]', { type, id });
}

export function formatRuntime(minutes: number | null | undefined): string | null {
	if (!minutes) return null;
	const hours = Math.floor(minutes / 60);
	const rest = minutes % 60;
	return hours ? `${hours}h ${rest.toString().padStart(2, '0')}m` : `${rest}m`;
}

export function formatDate(iso: string | null | undefined): string | null {
	if (!iso) return null;
	const date = new Date(`${iso}T00:00:00`);
	if (Number.isNaN(date.getTime())) return null;
	return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

export function formatRating(vote: number | null | undefined): string | null {
	return vote ? vote.toFixed(1) : null;
}

/** The original title, when it differs from the displayed (localized) one. */
export function alternateTitle(media: {
	title: string;
	original_title?: string | null;
}): string | null {
	return media.original_title && media.original_title !== media.title ? media.original_title : null;
}

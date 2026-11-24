// Kept free of `$app/*` imports: `src/params.ts` imports this and is loaded
// outside of Vite at build time.
import type { MediaType } from '#lib/api/client.ts';

const MEDIA_TYPE_LABELS: Record<MediaType, string> = {
	movie: 'Movie',
	tv: 'TV series'
};

export function isMediaType(value: string): value is MediaType {
	return Object.hasOwn(MEDIA_TYPE_LABELS, value);
}

export function mediaTypeLabel(type: MediaType): string {
	return MEDIA_TYPE_LABELS[type];
}

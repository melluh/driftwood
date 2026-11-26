import createClient from 'openapi-fetch';
import { handleSessionLost } from '#lib/auth/session.ts';
import type { paths } from './schema';

/** Typed client for the Driftwood API (served under `/api`, proxied in dev). */
export const api = createClient<paths>();

// Every API route except /api/auth/* needs a session.
api.use({
	onResponse({ request, response }) {
		if (response.status === 401 && !new URL(request.url).pathname.startsWith('/api/auth/')) {
			handleSessionLost();
		}
	}
});

export type {
	AuthConfig,
	CastMember,
	ContinueWatching,
	CurrentUser,
	DownloadStatus,
	Genre,
	LibraryAvailability,
	LibraryEpisode,
	LibraryFile,
	LibraryStatus,
	MediaDetails,
	MediaSummary,
	MediaType,
	MyListStatus,
	PlaybackAudioTrack,
	PlaybackCapabilities,
	PlaybackOffer,
	PlaybackSession,
	PlaybackSubtitleTrack,
	PlaybackTrickplay,
	PlaybackVersion,
	RankedRelease,
	Rejected,
	ReleaseNfo,
	ReleaseSearch,
	SearchStatus,
	SubtitleStatus,
	SubtitleTrack,
	TorrentRelease,
	WatchHistoryItem,
	WatchHistoryPage,
	WatchPlan,
	WatchProgress
} from './schema';

import createClient from 'openapi-fetch';
import type { paths } from './schema';

/** Typed client for the Driftwood API (served under `/api`, proxied in dev). */
export const api = createClient<paths>();

export type {
	CastMember,
	Genre,
	MediaDetails,
	MediaSummary,
	MediaType,
	SearchStatus
} from './schema';

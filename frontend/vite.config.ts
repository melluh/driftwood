import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const apiTarget = process.env.DRIFTWOOD_API_URL ?? 'http://localhost:8000';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// Single-page app: the API lives in the FastAPI backend.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		proxy: { '/api': apiTarget }
	}
});

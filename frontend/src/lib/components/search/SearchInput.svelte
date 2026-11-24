<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import Icon from '../ui/Icon.svelte';
	import Spinner from '../ui/Spinner.svelte';

	let {
		value = $bindable<string>(''),
		loading = false,
		...rest
	}: Omit<HTMLInputAttributes, 'value'> & { value?: string; loading?: boolean } = $props();
</script>

<label class="search-input">
	<span class="icon">
		{#if loading}
			<Spinner size="1em" label="Searching" />
		{:else}
			<Icon name="search" size="1em" />
		{/if}
	</span>
	<span class="visually-hidden">Search movies and TV</span>
	<!-- The input lives in a modal dialog, where autofocus is the expected behavior -->
	<!-- svelte-ignore a11y_autofocus -->
	<input
		autofocus
		bind:value
		type="search"
		autocomplete="off"
		spellcheck="false"
		placeholder="Search movies and TV…"
		{...rest}
	/>
</label>

<style>
	.search-input {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-4) var(--space-6);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: oklch(from var(--color-surface) l c h / 0.8);
		backdrop-filter: blur(12px);
		font-size: clamp(1.25rem, 2vw + 0.75rem, 2rem);
		transition: border-color var(--duration-fast);
	}

	.search-input:focus-within {
		border-color: var(--color-accent);
	}

	.icon {
		display: grid;
		place-items: center;
		color: var(--color-text-muted);
	}

	input {
		flex: 1;
		min-width: 0;
		border: 0;
		outline: 0;
		background: transparent;
		font-size: inherit;
	}

	input::placeholder {
		color: var(--color-text-faint);
	}

	input::-webkit-search-cancel-button {
		display: none;
	}
</style>

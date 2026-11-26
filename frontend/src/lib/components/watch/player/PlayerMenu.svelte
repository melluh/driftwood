<!-- A pick-one list over the player: subtitles, audio tracks, versions. -->
<script lang="ts" module>
	export type MenuOption = {
		id: number | null;
		label: string;
		detail?: string;
		disabled?: boolean;
		/** Shown instead of the detail, e.g. why the option can't be picked. */
		note?: string;
	};
</script>

<script lang="ts">
	import Icon from '#lib/components/ui/Icon.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	let {
		title,
		options,
		selected,
		loading = false,
		onselect
	}: {
		title: string;
		options: MenuOption[];
		selected: number | null;
		/** The selected option is still loading. */
		loading?: boolean;
		onselect: (id: number | null) => void;
	} = $props();
</script>

<div class="menu" role="menu" aria-label={title}>
	<h3>{title}</h3>
	<div class="options">
		{#each options as option (option.id)}
			{@const active = option.id === selected}
			<button
				type="button"
				role="menuitemradio"
				aria-checked={active}
				class:active
				disabled={option.disabled}
				onclick={() => onselect(option.id)}
			>
				<span class="mark" aria-hidden="true">
					{#if active && loading}
						<Spinner size="0.9rem" label="Loading" />
					{:else if active}
						<Icon name="check" />
					{/if}
				</span>
				<span class="text">
					<span class="label">{option.label}</span>
					{#if option.note}
						<span class="detail note">{option.note}</span>
					{:else if option.detail}
						<span class="detail">{option.detail}</span>
					{/if}
				</span>
			</button>
		{/each}
	</div>
</div>

<style>
	.menu {
		display: flex;
		flex-direction: column;
		width: min(20rem, calc(100vw - 2 * var(--space-4)));
		max-height: min(26rem, 60dvh);
		padding: var(--space-2);
		border: 1px solid oklch(100% 0 0 / 0.1);
		border-radius: var(--radius-md);
		background: oklch(from var(--color-surface) l c h / 0.92);
		backdrop-filter: blur(16px);
		box-shadow: var(--shadow-lg);
	}

	h3 {
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--color-text-faint);
	}

	.options {
		overflow-y: auto;
		overscroll-behavior: contain;
	}

	button {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-2) var(--space-3);
		border: none;
		border-radius: var(--radius-sm);
		background: none;
		text-align: left;
		cursor: pointer;
	}

	button:hover:not(:disabled) {
		background: var(--color-surface-hover);
	}

	button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}

	.mark {
		display: grid;
		place-items: center;
		flex-shrink: 0;
		width: 1.25rem;
		height: 1.5rem;
		color: var(--color-accent-strong);
	}

	.text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.label {
		font-size: var(--text-sm);
	}

	.active .label {
		font-weight: 600;
	}

	.detail {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}

	.note {
		color: var(--color-danger);
	}
</style>

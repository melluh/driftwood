<!-- Marks a freeleech release: downloading it doesn't count against your ratio. -->
<script lang="ts">
	let { compact = false }: { compact?: boolean } = $props();
</script>

<span
	class="badge"
	class:compact
	title="Freeleech: the download doesn't count against your ratio"
	aria-label={compact ? 'Freeleech' : undefined}
>
	{compact ? 'FL' : 'Freeleech'}
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		padding: 0.125rem var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-accent);
		color: var(--color-accent-contrast);
		font-size: var(--text-xs);
		font-weight: 700;
		letter-spacing: 0.02em;
		text-transform: none;
		white-space: nowrap;
	}

	.compact {
		padding: 0 0.4em;
		border-radius: var(--radius-sm);
		letter-spacing: 0.04em;
	}
</style>

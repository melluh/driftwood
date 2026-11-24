<script lang="ts">
	let { size = '1.25em', label = 'Loading' }: { size?: string; label?: string } = $props();
</script>

<span class="spinner" style:--size={size} role="status" aria-label={label}></span>

<style>
	.spinner {
		display: inline-block;
		width: var(--size);
		height: var(--size);
		border: 2px solid var(--color-border);
		border-top-color: var(--color-accent);
		border-radius: var(--radius-full);
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(1turn);
		}
	}
</style>

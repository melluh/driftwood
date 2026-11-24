<script lang="ts">
	import { page } from '$app/state';
	import PageSection from '#lib/components/layout/PageSection.svelte';
</script>

<div class="error">
	<PageSection title={page.status === 404 ? 'Not found' : 'Something went wrong'}>
		<p>{page.error?.message}</p>
	</PageSection>
</div>

<style>
	.error {
		padding-top: calc(var(--header-height) + var(--space-12));
		color: var(--color-text-muted);
	}
</style>

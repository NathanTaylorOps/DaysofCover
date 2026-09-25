<script lang="ts">
  // Stage 0 placeholder: proves the Docker image serves a real Svelte
  // build with zero toolchain on the visitor's end. The actual UI (shell,
  // board page, network view, ...) is Stage 6 -- see the build plan.
  type Health = { version: string; status: string; [key: string]: unknown };

  let health = $state<Health | null>(null);
  let healthError = $state("");

  async function checkHealth() {
    healthError = "";
    try {
      const res = await fetch("/health");
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      health = (await res.json()) as Health;
    } catch (err) {
      healthError = err instanceof Error ? err.message : String(err);
    }
  }
</script>

<main>
  <h1>Days of Cover</h1>
  <p>
    Supply chain stress test: how long can you keep shipping if a
    supplier, port or route goes down, and what is the cheapest fix.
  </p>
  <p class="placeholder-note">
    This is the Stage 0 placeholder page &mdash; it exists to prove the
    Docker image serves a real build. The actual tool lands in Stage 6.
  </p>

  <button onclick={checkHealth}>Check API health</button>

  {#if health}
    <pre class="health-ok">{JSON.stringify(health, null, 2)}</pre>
  {:else if healthError}
    <p class="health-error">Could not reach /health: {healthError}</p>
  {/if}
</main>

<style>
  main {
    max-width: 40rem;
    margin: 4rem auto;
    padding: 0 1.5rem;
    font-family:
      -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #1a1a1a;
  }

  h1 {
    font-size: 1.75rem;
    margin-bottom: 0.5rem;
  }

  .placeholder-note {
    color: #666;
    font-size: 0.9rem;
  }

  button {
    margin-top: 1rem;
    padding: 0.5rem 1rem;
    font-size: 0.95rem;
    cursor: pointer;
  }

  .health-ok {
    background: #f3f7f2;
    border: 1px solid #cfe3c9;
    border-radius: 4px;
    padding: 0.75rem;
    font-size: 0.85rem;
    overflow-x: auto;
  }

  .health-error {
    color: #a33;
  }
</style>

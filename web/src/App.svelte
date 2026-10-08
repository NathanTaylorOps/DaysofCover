<script lang="ts">
  import { onMount } from "svelte";

  type ExposureRow = {
    element_id: string;
    element_type: "node" | "lane";
    convergence_fraction: number;
    affected_customer_sku_pairs: number;
  };
  type ExposureReport = {
    dataset: string;
    synthetic: boolean;
    method: string;
    limitations: string;
    nodes: number;
    lanes: number;
    rows: ExposureRow[];
  };

  type ElementCatalog = { nodes: { id: string; name: string }[]; lanes: { id: string; origin_id: string; destination_id: string }[] };

  let report = $state<ExposureReport | null>(null);
  let catalog = $state<ElementCatalog | null>(null);
  let error = $state("");
  let loading = $state(true);
  let filter = $state<"all" | "node" | "lane">("all");
  let search = $state("");
  let selected = $state<ExposureRow | null>(null);
  let requestController: AbortController | null = null;
  let sortBy = $state<"exposure" | "element" | "pairs">("exposure");
  let sortDescending = $state(true);

  const filtered = $derived.by(() => {
    const rows = (report?.rows ?? []).filter(
      (row) =>
        (filter === "all" || row.element_type === filter) &&
        (row.element_id.toLowerCase().includes(search.trim().toLowerCase()) ||
          elementLabel(row).toLowerCase().includes(search.trim().toLowerCase()))
    );
    const direction = sortDescending ? -1 : 1;
    return rows.sort((left, right) => {
      if (sortBy === "element") {
        return direction * left.element_id.localeCompare(right.element_id);
      }
      const leftValue = sortBy === "pairs" ? left.affected_customer_sku_pairs : left.convergence_fraction;
      const rightValue = sortBy === "pairs" ? right.affected_customer_sku_pairs : right.convergence_fraction;
      return direction * (leftValue - rightValue) || left.element_id.localeCompare(right.element_id);
    });
  });

  const selectedVisible = $derived(selected !== null && filtered.some((row) => row.element_id === selected?.element_id && row.element_type === selected?.element_type));

  function setSort(column: "exposure" | "element" | "pairs") {
    if (sortBy === column) {
      sortDescending = !sortDescending;
    } else {
      sortBy = column;
      sortDescending = column !== "element";
    }
  }

  function clearFilters() {
    filter = "all";
    search = "";
  }

  function selectRow(row: ExposureRow) {
    selected = row;
  }

  function elementLabel(row: ExposureRow) {
    if (row.element_type === "node") {
      return catalog?.nodes.find((node) => node.id === row.element_id)?.name ?? row.element_id;
    }
    const lane = catalog?.lanes.find((item) => item.id === row.element_id);
    if (!lane) return row.element_id;
    const origin = catalog?.nodes.find((node) => node.id === lane.origin_id)?.name ?? lane.origin_id;
    const destination = catalog?.nodes.find((node) => node.id === lane.destination_id)?.name ?? lane.destination_id;
    return `${origin} → ${destination}`;
  }

  function isElementCatalog(value: unknown): value is ElementCatalog {
    if (typeof value !== "object" || value === null) return false;
    const item = value as Record<string, unknown>;
    return Array.isArray(item.nodes) && item.nodes.every((node: unknown) =>
      typeof node === "object" && node !== null &&
      typeof (node as Record<string, unknown>).id === "string" &&
      typeof (node as Record<string, unknown>).name === "string") &&
      Array.isArray(item.lanes) && item.lanes.every((lane: unknown) =>
      typeof lane === "object" && lane !== null &&
      typeof (lane as Record<string, unknown>).id === "string" &&
      typeof (lane as Record<string, unknown>).origin_id === "string" &&
      typeof (lane as Record<string, unknown>).destination_id === "string");
  }

  async function loadExposure() {
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    loading = true;
    error = "";
    try {
      const response = await fetch("/api/example/exposure", { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload: unknown = await response.json();
      if (!isExposureReport(payload)) throw new Error("Unexpected analysis response format");
      report = payload;
      selected = payload.rows[0] ?? null;
      catalog = null;
      try {
        const catalogResponse = await fetch("/api/example/elements", { signal: controller.signal });
        if (catalogResponse.ok) {
          const catalogPayload: unknown = await catalogResponse.json();
          if (isElementCatalog(catalogPayload)) catalog = catalogPayload;
        }
      } catch (catalogError) {
        if (controller.signal.aborted) throw catalogError;
        // Element IDs remain usable when the optional metadata request fails.
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        error = cause instanceof Error ? cause.message : String(cause);
      }
    } finally {
      if (requestController === controller) {
        loading = false;
        requestController = null;
      }
    }
  }

  onMount(() => {
    void loadExposure();
    return () => requestController?.abort();
  });

  function isExposureReport(value: unknown): value is ExposureReport {
    if (typeof value !== "object" || value === null) return false;
    const item = value as Record<string, unknown>;
    if (typeof item.dataset !== "string" || typeof item.synthetic !== "boolean" ||
        typeof item.method !== "string" || typeof item.limitations !== "string" ||
        typeof item.nodes !== "number" || typeof item.lanes !== "number" ||
        !Array.isArray(item.rows)) return false;
    return item.rows.every((row: unknown) => {
      if (typeof row !== "object" || row === null) return false;
      const entry = row as Record<string, unknown>;
      return typeof entry.element_id === "string" &&
        (entry.element_type === "node" || entry.element_type === "lane") &&
        typeof entry.convergence_fraction === "number" &&
        Number.isFinite(entry.convergence_fraction) &&
        entry.convergence_fraction >= 0 && entry.convergence_fraction <= 1 &&
        typeof entry.affected_customer_sku_pairs === "number" &&
        Number.isInteger(entry.affected_customer_sku_pairs) &&
        entry.affected_customer_sku_pairs >= 0;
    });
  }

  function percentage(value: number) {
    return `${(value * 100).toFixed(1)}%`;
  }
</script>

<svelte:head>
  <title>Days of Cover | Network Exposure</title>
  <meta name="description" content="Structural supply-chain dependency analysis of a synthetic manufacturing network." />
</svelte:head>

<div class="shell">
  <aside class="sidebar">
    <div class="brand"><span class="brand-mark">DC</span><div><strong>DAYS OF COVER</strong><small>Supply-chain intelligence</small></div></div>
    <div class="nav-label">WORKSPACE</div>
    <div class="nav-active">◈ &nbsp; Network exposure</div>
    <div class="nav-label secondary">ANALYSIS STATUS</div>
    <p class="sidebar-note">Structural dependency screening is available. Inventory coverage, simulation and mitigation optimisation are not connected to this dashboard.</p>
    <div class="sidebar-bottom">RESEARCH &amp; DECISION SUPPORT<br /><span>Technical demonstration</span></div>
  </aside>

  <main>
    <header class="topbar"><span>ANALYTICS / NETWORK EXPOSURE</span><span class="status"><span class="status-dot"></span> Synthetic example</span></header>
    <div class="content">
      <div class="heading"><div><div class="eyebrow">SUPPLY NETWORK ANALYSIS</div><h1>Structural exposure</h1><p>Identify nodes and transport lanes whose removal disconnects customer-product supply paths.</p></div><span class="mode-tag">READ-ONLY ANALYSIS</span></div>

      {#if loading}
        <section class="panel message" aria-live="polite">Loading structural analysis…</section>
      {:else if error}
        <section class="panel message error" role="alert"><strong>Analysis unavailable</strong><p>Unable to load the example network: {error}</p><button onclick={loadExposure}>Retry</button></section>
      {:else if report}
        <div class="metrics" aria-label="Network summary">
          <div class="metric"><span>NETWORK</span><strong>{report.dataset}</strong><small>Synthetic reference case</small></div>
          <div class="metric"><span>NODES</span><strong>{report.nodes}</strong><small>Facilities and network points</small></div>
          <div class="metric"><span>TRANSPORT LANES</span><strong>{report.lanes}</strong><small>Directed connections</small></div>
          <div class="metric"><span>HIGHEST EXPOSURE</span><strong>{report.rows.length ? percentage(Math.max(...report.rows.map((row) => row.convergence_fraction))) : "N/A"}</strong><small>Structural value-weighted share</small></div>
        </div>
        <div class="analysis-layout">
          <section class="panel ranking">
            <div class="panel-head"><div><h2>Dependency ranking</h2><p>Structural exposure of customer/SKU paths. Select column headings to sort.</p></div><span class="count">{filtered.length} ELEMENTS</span></div>
            <div class="controls"><div class="tabs" role="group" aria-label="Element type"><button class:active={filter === "all"} onclick={() => filter = "all"}>All</button><button class:active={filter === "node"} onclick={() => filter = "node"}>Nodes</button><button class:active={filter === "lane"} onclick={() => filter = "lane"}>Lanes</button></div><input aria-label="Search network elements" placeholder="Search ID or name…" bind:value={search} /></div>
            <div class="table-wrap"><table><thead><tr><th aria-sort={sortBy === "element" ? (sortDescending ? "descending" : "ascending") : "none"}><button class="sort-button" onclick={() => setSort("element")}>ELEMENT {sortBy === "element" ? (sortDescending ? "↓" : "↑") : ""}</button></th><th>TYPE</th><th aria-sort={sortBy === "exposure" ? (sortDescending ? "descending" : "ascending") : "none"}><button class="sort-button" onclick={() => setSort("exposure")}>EXPOSURE {sortBy === "exposure" ? (sortDescending ? "↓" : "↑") : ""}</button></th><th class="right" aria-sort={sortBy === "pairs" ? (sortDescending ? "descending" : "ascending") : "none"}><button class="sort-button" onclick={() => setSort("pairs")}>AFFECTED PAIRS {sortBy === "pairs" ? (sortDescending ? "↓" : "↑") : ""}</button></th></tr></thead><tbody>
              {#each filtered as row (`${row.element_type}:${row.element_id}`)}
                <tr class:selected={selected?.element_id === row.element_id && selected?.element_type === row.element_type}>
                  <td class="element"><button class="element-button" aria-pressed={selected?.element_id === row.element_id} onclick={() => selectRow(row)}>{row.element_id}</button>{#if elementLabel(row) !== row.element_id}<span class="element-label">{elementLabel(row)}</span>{/if}</td><td><span class="type">{row.element_type}</span></td>
                  <td><div class="exposure"><span class="bar-track"><span class="bar" style:width={percentage(row.convergence_fraction)}></span></span><span>{percentage(row.convergence_fraction)}</span></div></td>
                  <td class="right">{row.affected_customer_sku_pairs}</td>
                </tr>
              {:else}
                <tr><td colspan="4" class="empty">No matching elements. <button class="clear-button" onclick={clearFilters}>Clear filters</button></td></tr>
              {/each}
            </tbody></table></div>
          </section>
          <aside class="panel detail" aria-live="polite"><div class="eyebrow">ELEMENT INSPECTOR</div>{#if selected && selectedVisible}<h2>{elementLabel(selected)}</h2>{#if elementLabel(selected) !== selected.element_id}<p class="detail-id">{selected.element_id}</p>{/if}<span class="type">{selected.element_type}</span><div class="detail-stat"><span>Structural exposure</span><strong>{percentage(selected.convergence_fraction)}</strong></div><div class="detail-stat"><span>Disconnected customer/SKU pairs</span><strong>{selected.affected_customer_sku_pairs}</strong></div><p>This screen tests whether qualified supply paths remain when the selected element is removed. It does not estimate when stock runs out.</p>{:else if selected}<p>The selected element is hidden by the current filters. Choose a visible element or <button class="clear-button" onclick={clearFilters}>clear filters</button> to inspect it.</p>{:else}<p>Select an element to inspect its dependency exposure.</p>{/if}</aside>
        </div>
        <section class="method"><strong>Methodology &amp; limitations</strong><p>{report.method}. {report.limitations} This is a synthetic example, not an assessment of an operating business.</p></section>
      {/if}
      <footer>Days of Cover · Structural analysis preview · No operational data uploaded</footer>
    </div>
  </main>
</div>

<style>
  :global(*){box-sizing:border-box}
  :global(body){margin:0;background:#f4f6f9;color:#17253a;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
  :global(button),:global(input){font:inherit}
  .shell{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh;min-width:0}
  .sidebar{background:#11233b;color:#fff;padding:28px 18px;display:flex;flex-direction:column}
  .brand{display:flex;gap:12px;align-items:center;padding:0 8px 42px}
  .brand-mark{display:grid;place-items:center;width:40px;height:40px;background:#2b76bd;border-radius:9px;font-weight:800}
  .brand strong{display:block;font-size:12px;letter-spacing:1.2px}.brand small{display:block;color:#94a8c2;font-size:11px;margin-top:5px}
  .nav-label{color:#8295af;font-size:10px;letter-spacing:1.5px;font-weight:750;padding:0 12px;margin-bottom:15px}
  .nav-label.secondary{margin-top:42px}
  .nav-active{background:#243c58;padding:13px 12px;border-radius:7px;font-size:13px;font-weight:650}
  .sidebar-note{color:#b0bfd1;font-size:12px;line-height:1.7;padding:0 12px}
  .sidebar-bottom{margin-top:auto;border-top:1px solid #2c4058;padding:22px 10px 0;font-size:10px;letter-spacing:1px;line-height:2;color:#a7b9cf}.sidebar-bottom span{color:#6d88a8}
  main{min-width:0}.topbar{height:64px;background:#fff;border-bottom:1px solid #e2e7ee;display:flex;align-items:center;justify-content:space-between;padding:0 38px;font-size:11px;font-weight:750;letter-spacing:1px;color:#7d8a9b}
  .status{display:flex;align-items:center;gap:9px}.status-dot{width:8px;height:8px;background:#2c9c80;border-radius:50%}
  .content{max-width:1440px;padding:40px 38px;margin:auto}
  .heading{display:flex;justify-content:space-between;gap:24px;align-items:center;margin-bottom:32px}
  .eyebrow{color:#3879b7;font-size:10px;font-weight:800;letter-spacing:1.7px}
  h1{font-size:32px;letter-spacing:-1px;margin:9px 0}h2{font-size:17px;margin:0 0 7px}
  .heading p,.panel-head p{color:#6b7b8e;font-size:13px;line-height:1.6;margin:0}
  .mode-tag{white-space:nowrap;border:1px solid #d8e3ee;border-radius:5px;color:#55718e;padding:10px;font-size:10px;font-weight:750;letter-spacing:.8px}
  .metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:22px}
  .metric,.panel{background:#fff;border:1px solid #e1e7ee;border-radius:9px;box-shadow:0 2px 12px #18365b06}
  .metric{padding:23px}.metric span{font-size:10px;font-weight:750;letter-spacing:1px;color:#7c8b9d;display:block}
  .metric strong{display:block;font-size:28px;letter-spacing:-.7px;margin:11px 0 4px;overflow-wrap:anywhere}.metric:first-child strong{font-size:17px;letter-spacing:0;margin-top:17px}
  .metric small{color:#8190a2;font-size:11px}
  .analysis-layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:20px;min-width:0}.ranking{min-width:0}
  .panel-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:24px 24px 19px}
  .count{color:#8795a6;font-size:10px;letter-spacing:1px;font-weight:700;white-space:nowrap}
  .controls{display:flex;justify-content:space-between;gap:12px;padding:0 24px 20px}
  .tabs{display:flex;background:#f1f4f8;border-radius:6px;padding:3px}.tabs button{border:0;background:transparent;color:#65778b;padding:8px 13px;border-radius:5px;cursor:pointer;font-size:12px}.tabs button.active{background:#fff;color:#215e98;box-shadow:0 1px 4px #12243b1a;font-weight:700}
  input{border:1px solid #dce4ec;border-radius:6px;padding:9px 12px;min-width:0;width:205px;font-size:12px}
  .table-wrap{overflow-x:auto;max-width:100%}table{border-collapse:collapse;width:100%;font-size:12px}th{text-align:left;color:#8a98a9;font-size:10px;letter-spacing:.8px;background:#f8fafc;padding:14px 23px;white-space:nowrap}td{padding:15px 23px;border-top:1px solid #edf0f4}tbody tr{cursor:default}tbody tr:hover,tbody tr.selected{background:#f0f6fc}.element{font-weight:700;color:#294d75;overflow-wrap:anywhere}.element-button{background:none;border:0;padding:4px 0;color:inherit;font-weight:inherit;text-align:left;cursor:pointer;text-decoration:underline;text-underline-offset:3px}.element-label{display:block;color:#70849a;font-size:11px;font-weight:400;margin-top:4px;line-height:1.4}.clear-button{border:0;background:transparent;color:#215e98;text-decoration:underline;text-underline-offset:2px;cursor:pointer;font-weight:650;padding:4px}.clear-button:focus-visible{outline:2px solid #1e75bb;outline-offset:3px}.detail-id{font-family:ui-monospace,monospace;font-size:11px!important;margin:0 0 12px!important;color:#73879d!important}.element-button:focus-visible,.sort-button:focus-visible,.tabs button:focus-visible{outline:2px solid #1e75bb;outline-offset:3px}.sort-button{background:none;border:0;padding:0;color:inherit;font-size:inherit;font-weight:inherit;letter-spacing:inherit;cursor:pointer;text-align:inherit}.type{display:inline-block;text-transform:uppercase;font-size:10px;letter-spacing:.6px;background:#eaf0f6;color:#55718d;padding:5px 8px;border-radius:4px}.right{text-align:right}
  .exposure{display:flex;gap:10px;align-items:center;min-width:150px}.exposure>span:last-child{min-width:43px;text-align:right;font-weight:650}.bar-track{height:7px;background:#e8edf3;border-radius:8px;flex:1;overflow:hidden}.bar{display:block;background:#3b82bc;height:100%;border-radius:8px}.empty{text-align:center;color:#7b8b9d;padding:32px}
  .detail{padding:25px;align-self:start}.detail h2{overflow-wrap:anywhere;margin:16px 0 12px;font-size:20px}.detail-stat{border-top:1px solid #e8edf3;margin-top:22px;padding-top:18px}.detail-stat span{display:block;font-size:11px;color:#78899b}.detail-stat strong{display:block;font-size:28px;margin-top:6px}.detail p{font-size:12px;color:#718399;line-height:1.8;margin-top:24px}
  .method{border-left:3px solid #397cb9;background:#eaf1f8;padding:18px 22px;margin-top:23px;border-radius:0 6px 6px 0}.method strong{font-size:12px}.method p{font-size:12px;color:#58718b;line-height:1.7;margin:8px 0 0}
  .message{padding:35px}.error{color:#a33232}.error button{padding:9px 18px;cursor:pointer}
  footer{font-size:11px;color:#8b9aab;padding:30px 0}
  @media(max-width:1100px){.metrics{grid-template-columns:repeat(2,1fr)}.analysis-layout{grid-template-columns:1fr}.detail{display:block}}
  @media(max-width:700px){.shell{grid-template-columns:1fr}.sidebar{padding:15px;display:block}.brand{padding:0}.nav-label,.nav-active,.sidebar-note,.sidebar-bottom{display:none}.topbar{height:50px;padding:0 18px}.content{padding:24px 16px}.heading{align-items:start;flex-direction:column}.metrics{gap:10px}.metric{padding:16px}.metric strong{font-size:23px}.controls{flex-direction:column}.panel-head{flex-wrap:wrap}.tabs{max-width:100%}input{width:100%}th,td{padding:12px}.mode-tag{font-size:9px}}
</style>

<script lang="ts">
  import { onMount } from "svelte";

  type Config = {
    plant_node_id: string; sku_id: string; component_part_id: string;
    initial_component_units: number; initial_finished_units: number;
    daily_demand_units: number; horizon_days: number;
    production_capacity_per_week: number; disruption_start_day: number;
    disruption_duration_days: number; disruption_severity_fraction: number; seed: number;
  };
  type RequestPayload = { network: Record<string, unknown>; config: Config };
  type Daily = { day: number; demand_units: number; fulfilled_units: number; backlog_units: number };
  type Outcome = { total_demand_units: number; total_fulfilled_units: number; service_fraction: number; daily: Daily[] };
  type Comparison = {
    dataset: string; synthetic: boolean; element_id: string; horizon_days: number; seed: number;
    baseline: Outcome; disrupted: Outcome; fulfillment_delta_units: number;
    assumptions: string[]; limitations: string[];
  };

  let example = $state<RequestPayload | null>(null);
  let result = $state<Comparison | null>(null);
  let loading = $state(true);
  let running = $state(false);
  let error = $state("");
  let aborter: AbortController | null = null;

  type NumericConfigKey = Exclude<keyof Config, "plant_node_id" | "sku_id" | "component_part_id">;
  const fields: { key: NumericConfigKey; label: string; step: string; min: number; max: number }[] = [
    { key: "initial_component_units", label: "Component inventory (units)", step: "1", min: 0, max: 1000000000 },
    { key: "initial_finished_units", label: "Finished inventory (units)", step: "1", min: 0, max: 1000000000 },
    { key: "daily_demand_units", label: "Daily demand (units)", step: "1", min: 0, max: 1000000000 },
    { key: "horizon_days", label: "Analysis horizon (days)", step: "1", min: 1, max: 90 },
    { key: "production_capacity_per_week", label: "Production capacity (units/week)", step: "1", min: 0, max: 1000000000 },
    { key: "disruption_start_day", label: "Disruption begins (day 0 = first day)", step: "1", min: 0, max: 90 },
    { key: "disruption_duration_days", label: "Disruption duration (days)", step: "any", min: 0.01, max: 90 },
    { key: "disruption_severity_fraction", label: "Disruption severity (0–1)", step: "any", min: 0.01, max: 1 }
  ];
  function update(key: keyof Config, event: Event) {
    if (!example) return;
    const value = Number((event.currentTarget as HTMLInputElement).value);
    example = { ...example, config: { ...example.config, [key]: value } };
    result = null;
  }
  function validate(config: Config): string {
    for (const field of fields) {
      const value = config[field.key];
      if (!Number.isFinite(value) || value < field.min || value > field.max) return `${field.label} must be between ${field.min} and ${field.max}.`;
      if ((field.key === "horizon_days" || field.key === "disruption_start_day") && !Number.isInteger(value)) return `${field.label} must be a whole number.`;
    }
    if (config.disruption_start_day >= config.horizon_days) return "Disruption must begin within the analysis horizon.";
    return "";
  }
  function isComparison(value: unknown): value is Comparison {
    if (!value || typeof value !== "object") return false;
    const data = value as Record<string, unknown>;
    const finite = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
    if (!Number.isInteger(data.horizon_days) || !finite(data.horizon_days) || data.horizon_days < 1 || data.horizon_days > 90 ||
        !Number.isInteger(data.seed) || !finite(data.seed) || data.seed < 0 ||
        typeof data.dataset !== "string" || typeof data.element_id !== "string" ||
        typeof data.synthetic !== "boolean" || !finite(data.fulfillment_delta_units) ||
        !Array.isArray(data.assumptions) || !data.assumptions.every(x => typeof x === "string") ||
        !Array.isArray(data.limitations) || !data.limitations.every(x => typeof x === "string")) return false;

    const validOutcome = (item: unknown): item is Outcome => {
      if (!item || typeof item !== "object") return false;
      const run = item as Record<string, unknown>;
      if (!finite(run.total_demand_units) || !finite(run.total_fulfilled_units) ||
          !finite(run.service_fraction) || run.service_fraction < 0 || run.service_fraction > 1 ||
          !Array.isArray(run.daily) || run.daily.length !== data.horizon_days) return false;
      let demand = 0;
      let fulfilled = 0;
      for (const [index, item] of run.daily.entries()) {
        if (!item || typeof item !== "object") return false;
        const day = item as Record<string, unknown>;
        if (day.day !== index || !finite(day.demand_units) || !finite(day.fulfilled_units) ||
            !finite(day.backlog_units) || day.demand_units < 0 || day.fulfilled_units < 0 ||
            day.backlog_units < 0) return false;
        demand += day.demand_units;
        fulfilled += day.fulfilled_units;
        if (Math.abs(day.backlog_units - (demand - fulfilled)) > 1e-7 * Math.max(1, demand)) return false;
      }
      return Math.abs(run.total_demand_units - demand) <= 1e-7 * Math.max(1, demand) &&
        Math.abs(run.total_fulfilled_units - fulfilled) <= 1e-7 * Math.max(1, fulfilled) &&
        Math.abs(run.service_fraction - (demand ? fulfilled / demand : 1)) <= 1e-7;
    };
    if (!validOutcome(data.baseline) || !validOutcome(data.disrupted)) return false;
    return Math.abs(data.baseline.total_demand_units - data.disrupted.total_demand_units) <=
      1e-7 * Math.max(1, data.baseline.total_demand_units) &&
      Math.abs(data.fulfillment_delta_units -
        (data.disrupted.total_fulfilled_units - data.baseline.total_fulfilled_units)) <=
      1e-7 * Math.max(1, data.baseline.total_fulfilled_units);
  }
  async function loadExample() {
    aborter?.abort();
    const controller = new AbortController();
    aborter = controller;
    loading = true; error = ""; result = null;
    try {
      const response = await fetch("/api/example/simulation/request", { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data: unknown = await response.json();
      if (!data || typeof data !== "object" || !("network" in data) || !("config" in data) ||
          !data.config || typeof data.config !== "object") throw new Error("Unexpected example configuration");
      example = data as RequestPayload;
    } catch (cause) {
      if (!controller.signal.aborted) error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (aborter === controller) { loading = false; aborter = null; }
    }
  }
  async function runScenario(event: SubmitEvent) {
    event.preventDefault();
    if (!example || running) return;
    error = validate(example.config);
    if (error) return;
    aborter?.abort();
    const controller = new AbortController();
    aborter = controller; running = true; result = null;
    try {
      const response = await fetch("/api/simulation/bounded", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(example), signal: controller.signal
      });
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        if (response.status === 422) message = "The API rejected these inputs. Review the scenario parameters.";
        if (response.status === 413) message = "The scenario request exceeds the API size limit.";
        throw new Error(message);
      }
      const data: unknown = await response.json();
      if (!isComparison(data)) throw new Error("Unexpected simulation response format");
      result = data;
    } catch (cause) {
      if (!controller.signal.aborted) error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (aborter === controller) { running = false; aborter = null; }
    }
  }
  const weeklyDemand = $derived((example?.config.daily_demand_units ?? 0) * 7);
  const weeklyCapacity = $derived(example?.config.production_capacity_per_week ?? 0);
  const capacityConstrained = $derived(weeklyDemand > weeklyCapacity && weeklyDemand > 0);
  const impactAbsent = $derived(result !== null && Math.abs(result.fulfillment_delta_units) < 0.0000001);
  function explainResult(): string {
    if (!result || !example) return "";
    if (impactAbsent && capacityConstrained) return "The disrupted and baseline runs fulfil the same number of units. Baseline capacity is already below demand, and existing finished stock can also mask the effect of a disruption. This comparison does not establish that the disruption has no operational consequences.";
    if (impactAbsent) return "The model shows no change in same-day fulfilment over this horizon. Existing inventory, disruption timing or other constraints may mask the impact; try a longer horizon or different inventory and capacity assumptions.";
    return "The disruption changes same-day fulfilment by " + result.fulfillment_delta_units.toLocaleString() + " units relative to baseline. Compare the daily bars and backlog to see when the runs diverge.";
  }
  function percent(value: number) { return `${(value * 100).toFixed(1)}%`; }
  function units(value: number) { return value.toLocaleString(undefined, { maximumFractionDigits: 2 }); }
  onMount(() => { void loadExample(); return () => aborter?.abort(); });
</script>

<svelte:head>
  <meta name="description" content="Illustrative deterministic single-component production disruption comparison." />
</svelte:head>

<div class="scenario">
  <div class="heading"><div><div class="eyebrow">BOUNDED SIMULATION</div><h1>Scenario comparison</h1><p>Compare same-day order fulfilment with and without a production disruption.</p></div><span class="tag">ILLUSTRATIVE MODEL</span></div>
  <p class="notice">This workspace starts with a synthetic single-plant, single-SKU example. Editable values do not make it an operational forecast. Structural exposure and scenario simulation are separate analyses.</p>
  {#if loading}
    <section class="panel message" role="status">Loading illustrative scenario…</section>
  {:else if !example}
    <section class="panel message" role="alert">Unable to load the scenario. {error} <button onclick={loadExample}>Retry</button></section>
  {:else}
    <form class="panel form" onsubmit={runScenario}>
      <div class="panel-title"><div><h2>Scenario inputs</h2><p>Adjust the bounded assumptions and rerun the comparison.</p></div><button type="button" class="secondary" onclick={loadExample} disabled={running}>Reset example</button></div>
      <div class="fields">
        {#each fields as field}
          <label><span>{field.label}</span><input type="number" required min={field.min} max={field.max} step={field.step} value={example.config[field.key]} oninput={event => update(field.key, event)} /></label>
        {/each}
      </div>
      <div class="capacity-summary" role="status">
        <strong>Capacity check</strong>
        <span>Weekly demand: {weeklyDemand.toLocaleString()} units · Baseline capacity: {weeklyCapacity.toLocaleString()} units/week</span>
        {#if capacityConstrained}
          <p>Baseline production capacity is below demand even before disruption. A disruption may have little additional effect on same-day service, especially while finished stock remains.</p>
        {:else}
          <p>Nominal weekly production capacity meets or exceeds demand. Component availability, batch sizes, lead time and finished inventory still affect service.</p>
        {/if}
      </div>
      <div class="form-bottom"><span>Plant: {example.config.plant_node_id} · SKU: {example.config.sku_id} · Component: {example.config.component_part_id}</span><button type="submit" disabled={running}>{running ? "Running comparison…" : "Run comparison"}</button></div>
    </form>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if result}
      <section aria-label="Scenario results" aria-live="polite">
        <div class="panel-title results-title"><div><h2>Comparison results</h2><p>Daily fulfilment is measured against new demand, not eventual backlog recovery.</p></div><span class="tag">ILLUSTRATIVE INPUTS</span></div>
        <div class="metrics">
          <div class="panel metric"><span>BASELINE SERVICE</span><strong>{percent(result.baseline.service_fraction)}</strong><small>{units(result.baseline.total_fulfilled_units)} / {units(result.baseline.total_demand_units)} units</small></div>
          <div class="panel metric"><span>DISRUPTED SERVICE</span><strong>{percent(result.disrupted.service_fraction)}</strong><small>{units(result.disrupted.total_fulfilled_units)} / {units(result.disrupted.total_demand_units)} units</small></div>
          <div class="panel metric"><span>FULFILMENT DIFFERENCE</span><strong>{result.fulfillment_delta_units > 0 ? "+" : ""}{units(result.fulfillment_delta_units)} units</strong><small>Disrupted minus baseline</small></div>
        </div>
        <div class="panel interpretation" role="status"><h2>What the comparison means</h2><p>{explainResult()}</p></div>
        <div class="panel chart-panel"><h2>Daily fulfilment comparison</h2><p>Bars show the share of each day's new demand fulfilled. Blue: baseline; dark: disrupted.</p>
          <div class="chart-key"><span><i class="baseline-key"></i>Baseline</span><span><i class="disrupted-key"></i>Disrupted</span></div>
          <div class="chart-scroll" role="region" aria-label="Daily fulfilment chart, scroll horizontally for additional days" tabindex="0"><div class="chart-grid" aria-hidden="true">
            {#each result.baseline.daily as day, i (day.day)}
              <div class="chart-day" title={`Day ${day.day}: baseline ${day.fulfilled_units}, disrupted ${result.disrupted.daily[i]?.fulfilled_units ?? 0} units`}>
                <div class="bar-pair"><div class="chart-bar baseline-bar" style:height={percent(day.demand_units ? Math.min(1,day.fulfilled_units / day.demand_units) : 1)}></div><div class="chart-bar disrupted-bar" style:height={percent(day.demand_units ? Math.min(1,(result.disrupted.daily[i]?.fulfilled_units ?? 0) / day.demand_units) : 1)}></div></div>
                <span>{day.day}</span>
              </div>
            {/each}
          </div></div>
          <p class="chart-note">Day numbers start at 0. Exact quantities and cumulative backlog appear in the table below.</p>
        </div>
        <div class="panel table-panel"><h2>Daily outcomes</h2><div class="table-wrap" role="region" aria-label="Daily outcome table, scroll horizontally for additional columns" tabindex="0"><table><caption>Daily demand, fulfilment and cumulative backlog, in units</caption><thead><tr><th>DAY</th><th>DEMAND</th><th>BASELINE FULFILLED</th><th>DISRUPTED FULFILLED</th><th>BASELINE BACKLOG</th><th>DISRUPTED BACKLOG</th></tr></thead><tbody>
          {#each result.baseline.daily as day, i (day.day)}
            <tr><th scope="row">{day.day}</th><td>{units(day.demand_units)}</td><td>{units(day.fulfilled_units)}</td><td>{units(result.disrupted.daily[i].fulfilled_units)}</td><td>{units(day.backlog_units)}</td><td>{units(result.disrupted.daily[i].backlog_units)}</td></tr>
          {/each}
        </tbody></table></div></div>
        <div class="notes"><section class="panel"><h2>Assumptions</h2><ul>{#each result.assumptions as item}<li>{item}</li>{/each}</ul></section><section class="panel"><h2>Limitations</h2><ul>{#each result.limitations as item}<li>{item}</li>{/each}</ul></section></div>
      </section>
    {/if}
  {/if}
</div>

<style>
  .scenario{max-width:1440px;margin:auto;padding:40px 38px;color:#17253a}
  .heading,.panel-title,.form-bottom{display:flex;justify-content:space-between;align-items:center;gap:20px}
  .heading{margin-bottom:22px}.eyebrow{color:#3879b7;font-size:10px;font-weight:800;letter-spacing:1.7px}
  h1{font-size:32px;letter-spacing:-1px;margin:9px 0}h2{font-size:17px;margin:0 0 7px}
  p{color:#64778b;font-size:13px;line-height:1.6;margin:0}.tag{border:1px solid #d8e3ee;color:#55718e;border-radius:5px;padding:10px;font-size:10px;font-weight:750;letter-spacing:.7px;white-space:nowrap}
  .notice{padding:14px 18px;background:#eaf1f8;border-left:3px solid #397cb9;border-radius:4px;margin-bottom:22px}
  .panel{background:white;border:1px solid #e1e7ee;border-radius:9px;box-shadow:0 2px 12px #18365b06}
  .form{padding:25px}.fields{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;margin:25px 0}
  label{display:flex;flex-direction:column;gap:8px;color:#53677d;font-size:12px;font-weight:650}
  input{width:100%;min-width:0;border:1px solid #dce4ec;border-radius:6px;padding:10px 12px;font:inherit;color:#17253a}
  button{border:0;border-radius:6px;background:#256ba7;color:white;padding:11px 18px;font:inherit;font-size:12px;font-weight:700;cursor:pointer}
  button.secondary{background:#eef3f8;color:#245d90}button:disabled{opacity:.6;cursor:wait}
  button:focus-visible,input:focus-visible{outline:2px solid #1e75bb;outline-offset:3px}
  .form-bottom{border-top:1px solid #edf0f4;padding-top:20px}.form-bottom span{font-size:11px;color:#7c8b9d;overflow-wrap:anywhere}
  .results-title{margin:30px 0 18px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:20px}
  .metric{padding:24px}.metric span{display:block;font-size:10px;font-weight:750;letter-spacing:1px;color:#7c8b9d}.metric strong{display:block;font-size:28px;margin:12px 0 5px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.metric small{color:#8190a2;font-size:11px}
  .table-panel{padding:24px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}th{text-align:left;background:#f8fafc;color:#8291a4;font-size:10px;letter-spacing:.5px;white-space:nowrap}td,th{padding:14px;border-bottom:1px solid #edf0f4}td{text-align:right;font-variant-numeric:tabular-nums}thead th:not(:first-child){text-align:right}tbody th{text-align:left;font-weight:650}caption{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
  .notes{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:20px}.notes .panel{padding:24px}li{color:#63788d;font-size:12px;line-height:1.7;margin:8px 0}.error{color:#a33232;margin:15px 0}.message{padding:30px}
  .capacity-summary{border:1px solid #dce6ef;background:#f5f9fc;padding:15px 18px;border-radius:6px;margin-bottom:20px;display:grid;gap:7px;font-size:12px;color:#49637d}
  .capacity-summary strong{color:#1d4468}.capacity-summary p{font-size:12px}
  .interpretation,.chart-panel{padding:24px;margin-bottom:20px}.interpretation{border-left:3px solid #3879b7}
  .chart-key{display:flex;gap:20px;margin:17px 0;font-size:12px;color:#64778b}.chart-key span{display:flex;align-items:center;gap:7px}.chart-key i{display:inline-block;width:12px;height:12px;border-radius:2px}
  .baseline-key,.baseline-bar{background:#4286bb}.disrupted-key,.disrupted-bar{background:#173c60}
  .chart-scroll{overflow-x:auto}.chart-grid{display:flex;gap:8px;align-items:end;min-width:max-content;height:190px;padding:8px 0 0;border-bottom:1px solid #dfe6ee}
  .chart-day{width:35px;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:end;gap:7px;font-size:10px;color:#6b7b8e}
  .bar-pair{height:150px;width:100%;display:flex;align-items:end;justify-content:center;gap:3px}
  .chart-bar{width:12px;min-height:0;border-radius:3px 3px 0 0}
  .chart-note{margin-top:12px;font-size:11px}
  .chart-scroll:focus-visible,.table-wrap:focus-visible{outline:2px solid #1e75bb;outline-offset:2px}
  @media(max-width:1000px){.fields{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:700px){.scenario{padding:24px 16px}.heading,.panel-title,.form-bottom{align-items:flex-start;flex-direction:column}.fields{grid-template-columns:1fr}.metrics,.notes{grid-template-columns:1fr}.metric{padding:18px}.tag{white-space:normal}}
</style>

const DATA_ROOT = "data";

const state = {
  manifest: null,
  searchIndex: [],
  sources: [],
  chunks: new Map(),
  browseLimit: 80,
};

const main = document.querySelector("#main-content");
const sectionNav = document.querySelector("#section-nav");

const SOURCE_LABELS = {
  transcriptomic: "Transcriptomic",
  epigenetic: "Epigenetic",
  longevityMap: "LongevityMap",
  genAge: "GenAge",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString("en-US");
}

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || value === "") return "Not reported";
  const number = Number(value);
  if (!Number.isFinite(number)) return escapeHtml(value);
  if (Math.abs(number) > 0 && (Math.abs(number) < 0.001 || Math.abs(number) >= 10000)) {
    return number.toExponential(2).replace("e+", "e");
  }
  return number.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function formatProbability(probability) {
  if (!probability || probability.value === null || probability.value === undefined) return "Not reported";
  if (probability.qualifier === "upper_bound") return escapeHtml(probability.display);
  if (probability.qualifier === "reported_zero") return "0 (source underflow)";
  const value = Number(probability.value);
  if (value < 0.001) return value.toExponential(2).replace("e+", "e");
  return value.toPrecision(3);
}

function sourceMarks(sources) {
  return sources
    .map(
      (source) =>
        `<span class="source-mark ${escapeHtml(source)}">${escapeHtml(SOURCE_LABELS[source] || source)}</span>`,
    )
    .join("");
}

function setSectionNav(items) {
  sectionNav.innerHTML = items
    .map((item) => `<a href="#${escapeHtml(item.id)}" data-section-target="${escapeHtml(item.id)}">${escapeHtml(item.label)}</a>`)
    .join("");
  sectionNav.querySelectorAll("[data-section-target]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      document.getElementById(link.dataset.sectionTarget)?.scrollIntoView({ behavior: "smooth" });
    });
  });
}

function setActiveNav(route) {
  const section = route.startsWith("gene/") || route === "genes" ? "genes" : route || "home";
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === section);
  });
}

function routeFromHash() {
  return window.location.hash.replace(/^#\/?/, "").split("?")[0] || "home";
}

function pageHeader(eyebrow, title, lede) {
  return `
    <header class="page-header" id="overview">
      <p class="eyebrow">${escapeHtml(eyebrow)}</p>
      <h1>${escapeHtml(title)}</h1>
      ${lede ? `<p class="lede">${escapeHtml(lede)}</p>` : ""}
    </header>`;
}

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
  return response.json();
}

async function loadGene(symbol) {
  const indexEntry = state.searchIndex.find((gene) => gene.symbol === symbol.toUpperCase());
  if (!indexEntry) return null;
  if (!state.chunks.has(indexEntry.chunk)) {
    state.chunks.set(indexEntry.chunk, await fetchJson(`${DATA_ROOT}/genes-${indexEntry.chunk}.json`));
  }
  return state.chunks.get(indexEntry.chunk)[indexEntry.symbol] || null;
}

function initializeSearch(panel, inputSelector, resultSelector, buttonSelector) {
  const input = panel.querySelector(inputSelector);
  const results = panel.querySelector(resultSelector);
  const button = panel.querySelector(buttonSelector);

  const findMatches = () => {
    const query = input.value.trim().toUpperCase();
    if (!query) {
      results.classList.remove("open");
      results.innerHTML = "";
      return [];
    }
    const prefix = [];
    const partial = [];
    for (const gene of state.searchIndex) {
      const symbol = gene.symbol.toUpperCase();
      const mouse = (gene.mouseSymbol || "").toUpperCase();
      const name = (gene.name || "").toUpperCase();
      if (symbol.startsWith(query) || mouse.startsWith(query)) prefix.push(gene);
      else if (symbol.includes(query) || mouse.includes(query) || name.includes(query)) partial.push(gene);
      if (prefix.length + partial.length >= 14) break;
    }
    const matches = [...prefix, ...partial].slice(0, 10);
    results.innerHTML = matches.length
      ? matches
          .map(
            (gene) => `
              <a class="search-result" href="#/gene/${encodeURIComponent(gene.symbol)}">
                <strong>${escapeHtml(gene.symbol)}${gene.mouseSymbol ? ` <span>⇄ ${escapeHtml(gene.mouseSymbol)}</span>` : ""}</strong>
                <span>${escapeHtml(gene.name || "Approved HGNC gene")}</span>
                <small>${escapeHtml(gene.location || "")}</small>
              </a>`,
          )
          .join("")
      : `<div class="search-result"><strong>No match</strong><span>Try a human or mouse gene symbol.</span><small></small></div>`;
    results.classList.add("open");
    return matches;
  };

  input.addEventListener("input", findMatches);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      const matches = findMatches();
      if (matches.length) window.location.hash = `#/gene/${matches[0].symbol}`;
    }
    if (event.key === "Escape") results.classList.remove("open");
  });
  button.addEventListener("click", () => {
    const matches = findMatches();
    if (matches.length) window.location.hash = `#/gene/${matches[0].symbol}`;
  });
}

function homeGeneCard(gene) {
  return `
    <a class="gene-card" href="#/gene/${encodeURIComponent(gene.symbol)}">
      <div class="gene-card-top">
        <span class="gene-card-symbol">${escapeHtml(gene.symbol)}</span>
        ${gene.mouseSymbol ? `<span class="ortholog-mini">Mouse ${escapeHtml(gene.mouseSymbol)}</span>` : ""}
      </div>
      <div class="gene-card-name">${escapeHtml(gene.name || "Approved HGNC gene")}</div>
      <div class="source-marks">${sourceMarks(gene.sources)}</div>
    </a>`;
}

function renderHome() {
  const featured = state.manifest.featuredGenes
    .map((symbol) => state.searchIndex.find((gene) => gene.symbol === symbol))
    .filter(Boolean);

  main.innerHTML = `
    ${pageHeader(
      "Open evidence reference",
      "Human Aging Atlas",
      "Search gene-level evidence across public transcriptomic, epigenetic, longevity, and curated ageing-gene sources.",
    )}

    <section class="search-panel" aria-label="Gene search">
      <label class="search-label" for="home-gene-search">Search by human symbol, mouse ortholog, or gene name</label>
      <div class="search-row">
        <input id="home-gene-search" type="search" autocomplete="off" placeholder="Examples: TP53, Trp53, FOXO3, FKBP5" />
        <button class="primary-button" id="home-search-button" type="button">Open gene record</button>
      </div>
      <div class="search-results" id="home-search-results" role="listbox"></div>
    </section>

    <section class="section-block landscape-section" id="evidence-landscape">
      <div class="section-heading-row">
        <h2>Evidence landscape</h2>
        <p>Distinct evidence types connected at the gene level</p>
      </div>
      <figure class="evidence-illustration full-width-artwork">
        <img src="assets/evidence-landscape.png" alt="Gene-level evidence from transcriptomic, epigenetic, LongevityMap, and GenAge sources" />
      </figure>
    </section>

    <section class="section-block" id="featured-genes">
      <div class="section-heading-row">
        <h2>Evidence-rich examples</h2>
        <a class="text-link" href="#/genes">Browse gene index</a>
      </div>
      <div class="gene-grid">${featured.map(homeGeneCard).join("")}</div>
    </section>`;

  initializeSearch(main, "#home-gene-search", "#home-search-results", "#home-search-button");
  setSectionNav([
    { id: "overview", label: "Overview" },
    { id: "evidence-landscape", label: "Evidence landscape" },
    { id: "featured-genes", label: "Example genes" },
  ]);
}

function renderGeneIndex() {
  main.innerHTML = `
    ${pageHeader(
      "Gene index",
      "Browse human genes",
      "Search approved human symbols, one-to-one mouse orthologs, or approved gene names.",
    )}
    <section class="filter-bar" id="gene-browser">
      <div class="filter-control grow">
        <label for="browse-query">Gene</label>
        <input id="browse-query" type="search" placeholder="TP53, Trp53, tumor protein p53" />
      </div>
      <div class="filter-control">
        <label for="browse-source">Public source</label>
        <select id="browse-source">
          <option value="all">All sources</option>
          ${Object.entries(SOURCE_LABELS).map(([key, label]) => `<option value="${key}">${label}</option>`).join("")}
        </select>
      </div>
    </section>
    <div class="result-summary" id="browse-summary"></div>
    <div class="table-wrap" id="gene-table-wrap"></div>
    <div class="pagination-row"><button class="secondary-button" id="show-more" type="button">Show more</button></div>`;

  const query = main.querySelector("#browse-query");
  const source = main.querySelector("#browse-source");
  const summary = main.querySelector("#browse-summary");
  const wrap = main.querySelector("#gene-table-wrap");
  const showMore = main.querySelector("#show-more");

  const draw = () => {
    const term = query.value.trim().toUpperCase();
    const sourceValue = source.value;
    const matches = state.searchIndex.filter((gene) => {
      const text = `${gene.symbol} ${gene.mouseSymbol || ""} ${gene.name || ""}`.toUpperCase();
      return (!term || text.includes(term)) && (sourceValue === "all" || gene.sources.includes(sourceValue));
    });
    const visible = matches.slice(0, state.browseLimit);
    summary.textContent = `${formatInteger(matches.length)} matching gene${matches.length === 1 ? "" : "s"}`;
    wrap.innerHTML = `
      <table class="data-table gene-index-table">
        <thead><tr><th>Human gene</th><th>Approved name</th><th>Human locus</th><th>Mouse ortholog</th><th>Evidence sources</th></tr></thead>
        <tbody>
          ${visible
            .map(
              (gene) => `<tr>
                <td><a class="gene-link" href="#/gene/${encodeURIComponent(gene.symbol)}">${escapeHtml(gene.symbol)}</a></td>
                <td>${escapeHtml(gene.name || "Not reported")}</td>
                <td>${escapeHtml(gene.location || "Not reported")}</td>
                <td>${gene.mouseSymbol ? escapeHtml(gene.mouseSymbol) : "—"}</td>
                <td><div class="source-marks">${sourceMarks(gene.sources)}</div></td>
              </tr>`,
            )
            .join("")}
        </tbody>
      </table>`;
    showMore.hidden = visible.length >= matches.length;
  };

  query.addEventListener("input", () => {
    state.browseLimit = 80;
    draw();
  });
  source.addEventListener("change", () => {
    state.browseLimit = 80;
    draw();
  });
  showMore.addEventListener("click", () => {
    state.browseLimit += 80;
    draw();
  });
  draw();
  setSectionNav([
    { id: "overview", label: "Overview" },
    { id: "gene-browser", label: "Gene browser" },
  ]);
}

function sourceOverviewCard(key, value, detail) {
  return `
    <div class="source-overview-card ${escapeHtml(key)}">
      <span class="source-overview-label">${escapeHtml(SOURCE_LABELS[key])}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>`;
}

function transcriptomicSection(records) {
  if (!records.length) return "";
  const organisms = [...new Set(records.map((record) => record.organism))];
  const itpCount = records.filter((record) => record.cohort === "ITP").length;
  return `
    <section class="record-section" id="transcriptomic-evidence">
      <div class="section-heading-row">
        <div><p class="section-kicker">Public source</p><h2>Cross-species transcriptomic signatures</h2></div>
        <a class="source-link" href="${TRANSCRIPTOMIC_SOURCE}" target="_blank" rel="noreferrer">Source study</a>
      </div>
      <div class="evidence-facts">
        <span><strong>${formatInteger(records.length)}</strong> associations</span>
        <span><strong>${formatInteger(organisms.length)}</strong> organism contexts</span>
        ${itpCount ? `<span><strong>${formatInteger(itpCount)}</strong> ITP analyses</span>` : ""}
      </div>
      <p class="source-note">ITP records are mouse cohort analyses. Gene identity is linked to the human page through a one-to-one ortholog.</p>
      ${renderTable(
        ["Organism", "Analysis", "Endpoint", "Model", "Slope", "Adjusted P"],
        records,
        (record) => [
          record.organism,
          record.cohort,
          record.endpoint,
          record.model,
          `${formatNumber(record.slope)} (${record.direction})`,
          formatProbability(record.adjustedPValue),
        ],
      )}
    </section>`;
}

function epigeneticSection(ageRecords, mortalityRecords) {
  if (!ageRecords.length && !mortalityRecords.length) return "";
  const ageTable = ageRecords.length
    ? `
      <div class="evidence-subsection">
        <h3>Chronological-age CpGs</h3>
        ${renderTable(
          ["CpG", "CpG locus", "Beta", "SE", "P"],
          ageRecords,
          (record) => [
            record.cpg,
            `chr${record.cpgChromosome}:${record.cpgPosition}`,
            formatNumber(record.beta),
            formatNumber(record.standardError),
            formatProbability(record.pValue),
          ],
        )}
      </div>`
    : "";
  const mortalityTable = mortalityRecords.length
    ? `
      <div class="evidence-subsection">
        <h3>All-cause mortality CpGs</h3>
        ${renderTable(
          ["CpG", "CpG locus", "Hazard ratio", "95% CI", "P", "Sensitivity model"],
          mortalityRecords,
          (record) => {
            const sensitivity = record.sensitivityAnalysis;
            return [
              record.cpg,
              `chr${record.cpgChromosome}:${record.cpgPosition}`,
              formatNumber(record.hazardRatio),
              `${formatNumber(record.hazardRatioCiLow)}–${formatNumber(record.hazardRatioCiHigh)}`,
              formatProbability(record.pValue),
              sensitivity
                ? `HR ${formatNumber(sensitivity.hazardRatio)}; P ${formatProbability(sensitivity.pValue)}`
                : "Not reported",
            ];
          },
        )}
      </div>`
    : "";
  return `
    <section class="record-section" id="epigenetic-evidence">
      <div class="section-heading-row">
        <div><p class="section-kicker">Public source</p><h2>Human epigenetic associations</h2></div>
        <a class="source-link" href="${EPIGENETIC_SOURCE}" target="_blank" rel="noreferrer">Source study</a>
      </div>
      <p class="source-note">Coordinates identify CpG loci. Mortality sensitivity estimates come from the relatedness-adjusted model for the same CpG.</p>
      ${ageTable}${mortalityTable}
    </section>`;
}

function longevitySection(records) {
  if (!records.length) return "";
  return `
    <section class="record-section" id="longevity-evidence">
      <div class="section-heading-row">
        <div><p class="section-kicker">Public source</p><h2>LongevityMap associations</h2></div>
        <a class="source-link" href="${LONGEVITY_SOURCE}" target="_blank" rel="noreferrer">Open LongevityMap</a>
      </div>
      ${renderTable(
        ["Variant", "Population", "Association", "Reference"],
        records,
        (record) => [
          record.variants || "Not reported",
          record.population || "Not reported",
          record.association || "Significant",
          record.pubmedUrl
            ? { html: `<a href="${escapeHtml(record.pubmedUrl)}" target="_blank" rel="noreferrer">PubMed ${escapeHtml(record.pubmedId)}</a>` }
            : "Not reported",
        ],
      )}
    </section>`;
}

function genAgeSection(humanRecord, mouseRecords) {
  if (!humanRecord && !mouseRecords.length) return "";
  const human = humanRecord
    ? `<div class="curation-block">
        <span class="tag">Human candidate gene</span>
        <h3>${escapeHtml(humanRecord.sourceSymbol)}</h3>
        <p>${escapeHtml(humanRecord.geneName || "Expert-curated human ageing gene")}</p>
        ${humanRecord.evidenceBasis?.length ? `<p class="compact-meta">Evidence basis: ${humanRecord.evidenceBasis.map(escapeHtml).join(", ")}</p>` : ""}
      </div>`
    : "";
  const mouse = mouseRecords.length
    ? `<div class="evidence-subsection">
        <h3>Mouse lifespan evidence</h3>
        ${renderTable(
          ["Mouse gene", "Lifespan effect", "Longevity influence", "Average lifespan change"],
          mouseRecords,
          (record) => [
            record.mouseSymbol,
            record.lifespanEffect || "Not reported",
            record.longevityInfluence || "Not reported",
            record.averageLifespanChange === null ? "Not reported" : `${formatNumber(record.averageLifespanChange)}%`,
          ],
        )}
      </div>`
    : "";
  return `
    <section class="record-section" id="genage-evidence">
      <div class="section-heading-row">
        <div><p class="section-kicker">Public source</p><h2>GenAge</h2></div>
        <a class="source-link" href="${GENAGE_SOURCE}" target="_blank" rel="noreferrer">Open GenAge</a>
      </div>
      ${human}${mouse}
    </section>`;
}

function renderTable(headers, rows, rowRenderer) {
  const renderRows = (items) => items
    .map((row) => {
      const cells = rowRenderer(row);
      return `<tr>${cells
        .map((cell) => `<td>${cell && typeof cell === "object" && "html" in cell ? cell.html : escapeHtml(cell)}</td>`)
        .join("")}</tr>`;
    })
    .join("");
  const initial = rows.slice(0, 25);
  const remaining = rows.slice(25);
  return `
    <div class="table-wrap evidence-table-wrap">
      <table class="data-table">
        <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
        <tbody>${renderRows(initial)}</tbody>
      </table>
    </div>
    ${remaining.length
      ? `<details class="additional-records">
          <summary>Show ${formatInteger(remaining.length)} additional records</summary>
          <div class="table-wrap evidence-table-wrap">
            <table class="data-table">
              <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
              <tbody>${renderRows(remaining)}</tbody>
            </table>
          </div>
        </details>`
      : ""}`;
}

const TRANSCRIPTOMIC_SOURCE = "https://doi.org/10.1038/s41586-026-10542-3";
const EPIGENETIC_SOURCE = "https://doi.org/10.1186/s13073-023-01161-y";
const LONGEVITY_SOURCE = "https://genomics.senescence.info/longevity/";
const GENAGE_SOURCE = "https://genomics.senescence.info/genes/";

async function renderGene(symbol) {
  const gene = await loadGene(symbol);
  if (!gene) {
    renderNotFound("Gene record not found", "Try the gene index or search using an approved human or mouse symbol.");
    return;
  }

  const ortholog = gene.mouseOrtholog;
  const stats = gene.statistics;
  const evidence = gene.evidence;
  const sourceCards = [];
  if (evidence.transcriptomic.length) {
    sourceCards.push(sourceOverviewCard("transcriptomic", `${formatInteger(stats.transcriptomicRecords)} associations`, `${gene.coverage.transcriptomicContexts.length} analysis contexts`));
  }
  if (evidence.epigeneticAge.length || evidence.epigeneticMortality.length) {
    sourceCards.push(sourceOverviewCard("epigenetic", `${formatInteger(stats.epigeneticAgeCpGs + stats.epigeneticMortalityCpGs)} CpGs`, `${stats.epigeneticAgeCpGs} age · ${stats.epigeneticMortalityCpGs} mortality`));
  }
  if (evidence.longevityMap.length) {
    sourceCards.push(sourceOverviewCard("longevityMap", `${formatInteger(stats.longevityAssociations)} reports`, "Significant human associations"));
  }
  if (evidence.genAgeHuman || evidence.genAgeMouse.length) {
    const parts = [];
    if (evidence.genAgeHuman) parts.push("human curation");
    if (evidence.genAgeMouse.length) parts.push("mouse lifespan evidence");
    sourceCards.push(sourceOverviewCard("genAge", "GenAge evidence", parts.join(" · ")));
  }

  const summaryBlock = gene.summary
    ? `<section class="gene-summary" id="gene-function">
        <div>
          <p class="section-kicker">Gene function</p>
          <p>${escapeHtml(gene.summary)}</p>
        </div>
        <a href="${escapeHtml(gene.summarySource?.url || gene.annotation.ncbiUrl || "#")}" target="_blank" rel="noreferrer">NCBI Gene</a>
      </section>`
    : "";

  main.innerHTML = `
    <article class="gene-identity" id="overview">
      <p class="eyebrow">Human gene record</p>
      <div class="gene-title-line">
        <div>
          <h1>${escapeHtml(gene.symbol)}</h1>
          <p class="gene-approved-name">${escapeHtml(gene.annotation.approvedName || "Approved HGNC gene")}</p>
        </div>
        <div class="gene-locus"><span>Human locus</span><strong>${escapeHtml(gene.annotation.chromosomeLocation || "Not reported")}</strong></div>
      </div>
      ${ortholog
        ? `<div class="ortholog-banner">
            <div><span>Human</span><strong>${escapeHtml(gene.symbol)}</strong></div>
            <span class="ortholog-link" aria-label="maps to">⇄</span>
            <div><span>Mouse</span><strong>${escapeHtml(ortholog.mouseSymbol)}</strong></div>
            <p>One-to-one MGI/Alliance ortholog</p>
          </div>`
        : ""}
      <div class="gene-reference-links">
        <a href="${escapeHtml(gene.annotation.hgncUrl)}" target="_blank" rel="noreferrer">HGNC</a>
        ${gene.annotation.ncbiUrl ? `<a href="${escapeHtml(gene.annotation.ncbiUrl)}" target="_blank" rel="noreferrer">NCBI Gene</a>` : ""}
        ${ortholog?.mouseMgiId ? `<a href="https://www.informatics.jax.org/marker/${encodeURIComponent(ortholog.mouseMgiId)}" target="_blank" rel="noreferrer">MGI</a>` : ""}
      </div>
    </article>

    ${summaryBlock}

    <section class="section-block" id="evidence-overview">
      <div class="section-heading-row"><h2>Evidence overview</h2><p>Source-specific evidence, not a universal score</p></div>
      <div class="source-overview-grid">${sourceCards.join("")}</div>
    </section>

    ${transcriptomicSection(evidence.transcriptomic)}
    ${epigeneticSection(evidence.epigeneticAge, evidence.epigeneticMortality)}
    ${longevitySection(evidence.longevityMap)}
    ${genAgeSection(evidence.genAgeHuman, evidence.genAgeMouse)}
  `;

  const nav = [
    { id: "overview", label: gene.symbol },
    ...(summaryBlock ? [{ id: "gene-function", label: "Gene function" }] : []),
    { id: "evidence-overview", label: "Evidence overview" },
    ...(evidence.transcriptomic.length ? [{ id: "transcriptomic-evidence", label: "Transcriptomic" }] : []),
    ...(evidence.epigeneticAge.length || evidence.epigeneticMortality.length ? [{ id: "epigenetic-evidence", label: "Epigenetic" }] : []),
    ...(evidence.longevityMap.length ? [{ id: "longevity-evidence", label: "LongevityMap" }] : []),
    ...(evidence.genAgeHuman || evidence.genAgeMouse.length ? [{ id: "genage-evidence", label: "GenAge" }] : []),
  ];
  setSectionNav(nav);
}

function renderMethods() {
  main.innerHTML = `
    ${pageHeader(
      "Methods",
      "Evidence architecture",
      "Gene identity is harmonized, while source-specific study designs and statistics remain separate.",
    )}
    <section class="section-block" id="gene-selection">
      <h2>Gene selection</h2>
      <p>The demonstration release preserves curated GenAge and significant LongevityMap genes, then prioritizes additional genes with broader support across public sources, human evidence, analysis contexts, endpoints, replication, and statistical support.</p>
    </section>
    <section class="section-block" id="identity-mapping">
      <h2>Human–mouse identity</h2>
      <p>Pages are anchored to approved HGNC human symbols. Mouse identifiers are linked only when the MGI/Alliance homology report defines a one-to-one human–mouse relationship; ambiguous one-to-many classes are not forced.</p>
    </section>
    <section class="section-block" id="source-scope">
      <h2>Evidence scope</h2>
      <div class="method-steps">
        <div class="method-step"><h3>Transcriptomic</h3><p>All 18 source tables are evaluated. Displayed associations meet an FDR-adjusted P value threshold of 0.05. ITP is represented as a mouse cohort.</p></div>
        <div class="method-step"><h3>Epigenetic</h3><p>Primary chronological-age CpGs and primary all-cause mortality CpGs are gene-annotated. The relatedness-adjusted mortality estimate is attached as a sensitivity analysis for the same CpG.</p></div>
        <div class="method-step"><h3>Curated resources</h3><p>Significant human LongevityMap associations and GenAge human records are retained. Mouse GenAge lifespan records are linked through one-to-one orthology.</p></div>
      </div>
    </section>
    <section class="section-block" id="interpretation">
      <h2>Interpretation</h2>
      <p>No universal evidence score or causal rank is assigned. Effects, P values, cohort context, and curation status must be interpreted within the design of each source.</p>
    </section>`;
  setSectionNav([
    { id: "overview", label: "Overview" },
    { id: "gene-selection", label: "Gene selection" },
    { id: "identity-mapping", label: "Human–mouse mapping" },
    { id: "source-scope", label: "Evidence scope" },
    { id: "interpretation", label: "Interpretation" },
  ]);
}

function renderSources() {
  main.innerHTML = `
    ${pageHeader(
      "Sources",
      "Public evidence collections",
      "Each gene record links back to the study or curated resource from which the evidence was derived.",
    )}
    <div id="source-collections">
      ${state.sources
        .map(
          (source) => `<section class="source-entry ${escapeHtml(source.key)}">
            <p class="section-kicker">${escapeHtml(source.organisms.join(" · "))}</p>
            <h2>${escapeHtml(source.title)}</h2>
            <p>${escapeHtml(source.description)}</p>
            <a class="source-link" href="${escapeHtml(source.sourceUrl)}" target="_blank" rel="noreferrer">Open source</a>
          </section>`,
        )
        .join("")}
    </div>`;
  setSectionNav([
    { id: "overview", label: "Overview" },
    { id: "source-collections", label: "Collections" },
  ]);
}

function renderNotFound(title = "Page not found", message = "The requested atlas page is unavailable.") {
  main.innerHTML = `<div class="error-state"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(message)}</p><a class="primary-button" href="#/">Return to atlas</a></div>`;
  setSectionNav([]);
}

async function renderRoute() {
  const route = routeFromHash();
  setActiveNav(route);
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  if (route === "home") renderHome();
  else if (route === "genes") renderGeneIndex();
  else if (route === "methods") renderMethods();
  else if (route === "sources") renderSources();
  else if (route.startsWith("gene/")) await renderGene(decodeURIComponent(route.slice(5)).toUpperCase());
  else renderNotFound();
}

async function initialize() {
  try {
    [state.manifest, state.searchIndex, state.sources] = await Promise.all([
      fetchJson(`${DATA_ROOT}/manifest.json`),
      fetchJson(`${DATA_ROOT}/search-index.json`),
      fetchJson(`${DATA_ROOT}/sources.json`),
    ]);
    await renderRoute();
  } catch (error) {
    main.innerHTML = `<div class="error-state"><h1>Atlas data could not be loaded</h1><p>${escapeHtml(error.message)}</p></div>`;
  }
}

window.addEventListener("hashchange", renderRoute);
initialize();

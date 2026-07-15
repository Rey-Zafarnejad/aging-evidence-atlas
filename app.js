const DATA_ROOT = "data";

const state = {
  manifest: null,
  searchIndex: [],
  sources: [],
  chunks: new Map(),
  browseLimit: 25,
  browseSort: { key: "symbol", direction: "asc" },
  layerFilter: "all",
};

const main = document.querySelector("#main-content");
const sectionNav = document.querySelector("#section-nav");
const railLabel = document.querySelector(".rail-label");

const LAYER_DEFINITIONS = {
  genomics: { label: "Genomics", status: "active" },
  epigenomics: { label: "Epigenomics", status: "active" },
  transcriptomics: { label: "Transcriptomics", status: "active" },
  proteomics: { label: "Proteomics", status: "active" },
  metabolomics: { label: "Metabolomics", status: "planned", note: "Coming next" },
  integrative: { label: "Integrative", status: "planned", note: "IMM-AGE · coming next" },
};

const ACTIVE_LAYER_KEYS = Object.entries(LAYER_DEFINITIONS)
  .filter(([, layer]) => layer.status === "active")
  .map(([key]) => key);

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

function evidenceMarks(layers) {
  return layers
    .map(
      (layer) => {
        const label = LAYER_DEFINITIONS[layer.key]?.label || layer.key;
        const sourceText = layer.sources?.length ? ` (${layer.sources.join(" + ")})` : "";
        return `<span class="source-mark ${escapeHtml(layer.key)}">${escapeHtml(label + sourceText)}</span>`;
      },
    )
    .join("");
}

function setSectionNav(items, label = "Contents") {
  railLabel.textContent = label;
  sectionNav.innerHTML = items
    .map((item) => item.disabled
      ? `<div class="rail-planned" aria-disabled="true"><strong>${escapeHtml(item.label)}</strong>${item.note ? `<span>${escapeHtml(item.note)}</span>` : ""}</div>`
      : `<a href="#${escapeHtml(item.id)}" data-section-target="${escapeHtml(item.id)}">${escapeHtml(item.label)}</a>`)
    .join("");
  sectionNav.querySelectorAll("[data-section-target]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      document.getElementById(link.dataset.sectionTarget)?.scrollIntoView({ behavior: "smooth" });
    });
  });
}

function setAtlasLayerNav(onFilter) {
  railLabel.textContent = "Evidence layers";
  sectionNav.innerHTML = `
    <button class="rail-filter active" type="button" data-layer-filter="all">All evidence</button>
    ${ACTIVE_LAYER_KEYS.map(
      (key) => `<button class="rail-filter" type="button" data-layer-filter="${key}">${escapeHtml(LAYER_DEFINITIONS[key].label)}</button>`,
    ).join("")}
    ${["metabolomics", "integrative"].map(
      (key) => `<div class="rail-planned"><strong>${escapeHtml(LAYER_DEFINITIONS[key].label)}</strong><span>${escapeHtml(LAYER_DEFINITIONS[key].note)}</span></div>`,
    ).join("")}`;
  sectionNav.querySelectorAll("[data-layer-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.layerFilter = button.dataset.layerFilter;
      sectionNav.querySelectorAll("[data-layer-filter]").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      onFilter();
    });
  });
}

function setActiveNav(route) {
  const section = route.startsWith("gene/") || route === "genes" ? "home" : route || "home";
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

function renderHome() {
  main.innerHTML = `
    ${pageHeader(
      "Open gene-level evidence reference",
      "Human Aging Atlas",
      "Search ageing evidence across genomics, epigenomics, transcriptomics, and proteomics.",
    )}

    <section class="atlas-search-zone" id="atlas-search" aria-label="Gene search">
      <div class="atlas-search-heading">
        <p class="section-kicker">Atlas search</p>
        <h2>Find a human gene or mouse ortholog</h2>
      </div>
      <div class="atlas-search-row">
        <div class="filter-control grow">
          <label for="atlas-query">Search by human symbol, mouse ortholog, or approved gene name</label>
          <input id="atlas-query" type="search" autocomplete="off" placeholder="TP53, Trp53, tumor protein p53" />
        </div>
        <div class="filter-control mobile-layer-control">
          <label for="atlas-layer">Evidence layer</label>
          <select id="atlas-layer">
            <option value="all">All evidence</option>
            ${ACTIVE_LAYER_KEYS.map((key) => `<option value="${key}">${escapeHtml(LAYER_DEFINITIONS[key].label)}</option>`).join("")}
          </select>
        </div>
        <button class="primary-button" id="open-first-match" type="button">Open first match</button>
      </div>
    </section>

    <section class="atlas-index-section" id="atlas-index">
      <div class="section-heading-row">
        <h2>Gene atlas</h2>
        <p id="atlas-summary">Alphabetical reference</p>
      </div>
      <div class="table-wrap" id="atlas-table-wrap"></div>
      <div class="pagination-row"><button class="secondary-button" id="show-more" type="button">Show more</button></div>
    </section>`;

  const query = main.querySelector("#atlas-query");
  const layer = main.querySelector("#atlas-layer");
  const summary = main.querySelector("#atlas-summary");
  const wrap = main.querySelector("#atlas-table-wrap");
  const showMore = main.querySelector("#show-more");
  const openFirst = main.querySelector("#open-first-match");
  state.browseLimit = 25;
  state.browseSort = { key: "symbol", direction: "asc" };
  state.layerFilter = "all";

  const draw = () => {
    const term = query.value.trim().toUpperCase();
    const matches = state.searchIndex
      .filter((gene) => {
        const text = `${gene.symbol} ${gene.mouseSymbol || ""} ${gene.name || ""}`.toUpperCase();
        return (
          (!term || text.includes(term))
          && (state.layerFilter === "all" || gene.evidenceLayers.some((item) => item.key === state.layerFilter))
        );
      })
      .sort((left, right) => {
        const direction = state.browseSort.direction === "asc" ? 1 : -1;
        if (state.browseSort.key === "layers") {
          const difference = left.evidenceLayerCount - right.evidenceLayerCount;
          if (difference) return difference * direction;
          return left.symbol.localeCompare(right.symbol);
        }
        return left.symbol.localeCompare(right.symbol) * direction;
      });
    const visible = matches.slice(0, state.browseLimit);
    summary.textContent = term || state.layerFilter !== "all" ? "Filtered atlas entries" : state.browseSort.key === "symbol" ? "Alphabetical reference" : "Ordered by evidence-layer breadth";
    const symbolArrow = state.browseSort.key === "symbol" ? (state.browseSort.direction === "asc" ? " ↑" : " ↓") : "";
    const layerArrow = state.browseSort.key === "layers" ? (state.browseSort.direction === "asc" ? " ↑" : " ↓") : "";
    wrap.innerHTML = `
      <table class="data-table atlas-table">
        <thead><tr>
          <th aria-sort="${state.browseSort.key === "symbol" ? (state.browseSort.direction === "asc" ? "ascending" : "descending") : "none"}"><button class="sort-button" type="button" data-sort="symbol">Human gene${symbolArrow}</button></th>
          <th>Approved name</th>
          <th>Human locus</th>
          <th>Mouse ortholog</th>
          <th aria-sort="${state.browseSort.key === "layers" ? (state.browseSort.direction === "asc" ? "ascending" : "descending") : "none"}"><button class="sort-button" type="button" data-sort="layers">Evidence layers${layerArrow}</button></th>
        </tr></thead>
        <tbody>
          ${visible.length ? visible
            .map(
              (gene) => `<tr>
                <td><a class="gene-link" href="#/gene/${encodeURIComponent(gene.symbol)}">${escapeHtml(gene.symbol)}</a></td>
                <td title="${escapeHtml(gene.name || "Not reported")}">${escapeHtml(gene.name || "Not reported")}</td>
                <td>${escapeHtml(gene.location || "Not reported")}</td>
                <td>${gene.mouseSymbol ? escapeHtml(gene.mouseSymbol) : "—"}</td>
                <td><div class="source-marks">${evidenceMarks(gene.evidenceLayers)}</div></td>
              </tr>`,
            )
            .join("") : `<tr><td colspan="5">No matching gene record. Try another symbol, ortholog, name, or evidence layer.</td></tr>`}
        </tbody>
      </table>`;
    showMore.hidden = visible.length >= matches.length;
    wrap.querySelectorAll("[data-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.sort;
        if (state.browseSort.key === key) {
          state.browseSort.direction = state.browseSort.direction === "asc" ? "desc" : "asc";
        } else {
          state.browseSort = { key, direction: key === "layers" ? "desc" : "asc" };
        }
        state.browseLimit = 25;
        draw();
      });
    });
    return matches;
  };

  query.addEventListener("input", () => {
    state.browseLimit = 25;
    draw();
  });
  layer.addEventListener("change", () => {
    state.layerFilter = layer.value;
    state.browseLimit = 25;
    sectionNav.querySelectorAll("[data-layer-filter]").forEach((button) => {
      button.classList.toggle("active", button.dataset.layerFilter === state.layerFilter);
    });
    draw();
  });
  showMore.addEventListener("click", () => {
    state.browseLimit += 25;
    draw();
  });
  openFirst.addEventListener("click", () => {
    const matches = draw();
    if (matches.length) window.location.hash = `#/gene/${matches[0].symbol}`;
  });
  query.addEventListener("keydown", (event) => {
    if (event.key === "Enter") openFirst.click();
  });
  setAtlasLayerNav(() => {
    layer.value = state.layerFilter;
    state.browseLimit = 25;
    draw();
  });
  draw();
}

function sourceOverviewCard(key, label, value, detail) {
  return `
    <div class="source-overview-card ${escapeHtml(key)}">
      <span class="source-overview-label">${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>`;
}

function countLabel(value, singular, plural = `${singular}s`) {
  const count = Number(value || 0);
  return `${formatInteger(count)} ${count === 1 ? singular : plural}`;
}

function transcriptomicSection(records) {
  if (!records.length) return "";
  const organisms = [...new Set(records.map((record) => record.organism))];
  const itpCount = records.filter((record) => record.cohort === "ITP").length;
  return `
    <section class="record-section" id="transcriptomic-evidence">
      <div class="section-heading-row">
        <div><p class="section-kicker">Transcriptomics</p><h2>tAge</h2></div>
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
        <h3>cAge · chronological-age CpGs</h3>
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
        <h3>bAge · all-cause mortality CpGs</h3>
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
        <div><p class="section-kicker">Epigenomics</p><h2>cAge and bAge</h2></div>
        <a class="source-link" href="${EPIGENETIC_SOURCE}" target="_blank" rel="noreferrer">Source study</a>
      </div>
      <p class="source-note">Coordinates identify CpG loci. Mortality sensitivity estimates come from the relatedness-adjusted model for the same CpG.</p>
      ${ageTable}${mortalityTable}
    </section>`;
}

function longevitySubsection(records) {
  if (!records.length) return "";
  return `
    <div class="evidence-subsection source-subsection">
      <div class="subsection-heading-row">
        <h3>LongevityMap associations</h3>
        <a class="source-link" href="${LONGEVITY_SOURCE}" target="_blank" rel="noreferrer">Open source</a>
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
    </div>`;
}

function genAgeSubsection(humanRecord, mouseRecords) {
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
    <div class="evidence-subsection source-subsection">
      <div class="subsection-heading-row">
        <h3>GenAge</h3>
        <a class="source-link" href="${GENAGE_SOURCE}" target="_blank" rel="noreferrer">Open source</a>
      </div>
      ${human}${mouse}
    </div>`;
}

function genomicsSection(longevityRecords, humanRecord, mouseRecords) {
  if (!longevityRecords.length && !humanRecord && !mouseRecords.length) return "";
  return `
    <section class="record-section" id="genomic-evidence">
      <div class="section-heading-row">
        <div><p class="section-kicker">Genomics</p><h2>Curated ageing and longevity evidence</h2></div>
      </div>
      ${genAgeSubsection(humanRecord, mouseRecords)}
      ${longevitySubsection(longevityRecords)}
    </section>`;
}

function organAgeSection(records) {
  if (!records.length) return "";
  return `
    <section class="record-section" id="proteomic-evidence">
      <div class="section-heading-row">
        <div><p class="section-kicker">Proteomics</p><h2>OrganAge</h2></div>
        <a class="source-link" href="${ORGANAGE_SOURCE}" target="_blank" rel="noreferrer">Source study</a>
      </div>
      <p class="source-note">Organ assignment follows the published tissue-enriched protein sets. Selection frequency is the number of non-zero appearances across 500 bootstrapped organ-age models.</p>
      ${renderTable(
        ["Organ", "Protein target", "SomaScan SeqId", "Selected models", "Coefficient direction"],
        records,
        (record) => [
          record.organ,
          record.targetFullName || record.targetName || "Not reported",
          record.seqId,
          `${formatInteger(record.selectedModels)} of ${formatInteger(record.modelCount)}`,
          record.coefficientDirection,
        ],
      )}
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
const ORGANAGE_SOURCE = "https://doi.org/10.1038/s41586-023-06802-1";

async function renderGene(symbol) {
  const gene = await loadGene(symbol);
  if (!gene) {
    renderNotFound("Gene record not found", "Return to the atlas and search using an approved human or mouse symbol.");
    return;
  }

  const ortholog = gene.mouseOrtholog;
  const stats = gene.statistics;
  const evidence = gene.evidence;
  const sourceCards = [];
  const genomicSources = [];
  if (evidence.genAgeHuman || evidence.genAgeMouse.length) genomicSources.push("GenAge");
  if (evidence.longevityMap.length) genomicSources.push("LongevityMap");
  if (genomicSources.length) {
    sourceCards.push(sourceOverviewCard("genomics", `Genomics (${genomicSources.join(" + ")})`, countLabel(stats.longevityAssociations + stats.genAgeHumanRecords + stats.genAgeMouseRecords, "record"), "Curated ageing and longevity evidence"));
  }
  if (evidence.epigeneticAge.length || evidence.epigeneticMortality.length) {
    const sources = [];
    if (evidence.epigeneticAge.length) sources.push("cAge");
    if (evidence.epigeneticMortality.length) sources.push("bAge");
    sourceCards.push(sourceOverviewCard("epigenomics", `Epigenomics (${sources.join(" + ")})`, `${formatInteger(stats.epigeneticAgeCpGs + stats.epigeneticMortalityCpGs)} CpGs`, `${stats.epigeneticAgeCpGs} age · ${stats.epigeneticMortalityCpGs} mortality`));
  }
  if (evidence.transcriptomic.length) {
    sourceCards.push(sourceOverviewCard("transcriptomics", "Transcriptomics (tAge)", countLabel(stats.transcriptomicRecords, "association"), countLabel(gene.coverage.transcriptomicContexts.length, "analysis context")));
  }
  if (evidence.organAge.length) {
    sourceCards.push(sourceOverviewCard("proteomics", "Proteomics (OrganAge)", countLabel(stats.organAgeProteinOrganRecords, "protein-organ record"), countLabel(stats.organAgeOrgans.length, "organ model")));
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

    ${genomicsSection(evidence.longevityMap, evidence.genAgeHuman, evidence.genAgeMouse)}
    ${epigeneticSection(evidence.epigeneticAge, evidence.epigeneticMortality)}
    ${transcriptomicSection(evidence.transcriptomic)}
    ${organAgeSection(evidence.organAge)}
  `;

  const nav = [
    { id: "overview", label: gene.symbol },
    ...(summaryBlock ? [{ id: "gene-function", label: "Gene function" }] : []),
    { id: "evidence-overview", label: "Evidence overview" },
    ...(evidence.longevityMap.length || evidence.genAgeHuman || evidence.genAgeMouse.length ? [{ id: "genomic-evidence", label: "Genomics" }] : []),
    ...(evidence.epigeneticAge.length || evidence.epigeneticMortality.length ? [{ id: "epigenetic-evidence", label: "Epigenomics" }] : []),
    ...(evidence.transcriptomic.length ? [{ id: "transcriptomic-evidence", label: "Transcriptomics" }] : []),
    ...(evidence.organAge.length ? [{ id: "proteomic-evidence", label: "Proteomics" }] : []),
  ];
  setSectionNav(nav);
}

function renderMethods() {
  main.innerHTML = `
    ${pageHeader(
      "Methods",
      "Evidence architecture",
      "Evidence is organized by omics layer, while the study design and statistical unit of each source remain explicit.",
    )}
    <section class="section-block prose-section" id="entry-scope">
      <h2>Entry scope</h2>
      <p>Gene pages are assembled from source-backed records and grouped into four active evidence layers. Breadth across layers can be used to order the atlas table, but it is not a biological-importance score or a causal rank.</p>
    </section>
    <section class="section-block prose-section" id="identity-mapping">
      <h2>Human–mouse identity</h2>
      <p>Pages are anchored to approved HGNC human symbols. Mouse identifiers are linked only when the MGI/Alliance homology report defines a one-to-one human–mouse relationship; ambiguous one-to-many classes are not forced.</p>
    </section>
    <section class="section-block" id="source-scope">
      <h2>Evidence layers</h2>
      <div class="method-steps">
        <div class="method-step" id="method-genomics"><div class="method-step-content"><h3>Genomics</h3><p>GenAge contributes expert-curated human ageing genes and mouse lifespan evidence linked by one-to-one orthology. LongevityMap contributes curated significant human genetic-association reports. Gene labels identify GenAge, LongevityMap, or both.</p></div></div>
        <div class="method-step" id="method-epigenomics"><div class="method-step-content"><h3>Epigenomics</h3><p>cAge denotes gene-annotated CpGs associated with chronological age. bAge denotes gene-annotated CpGs associated with all-cause mortality; the relatedness-adjusted estimate is retained as a sensitivity analysis for the same CpG.</p></div></div>
        <div class="method-step" id="method-transcriptomics"><div class="method-step-content"><h3>Transcriptomics</h3><p>tAge records come from 18 age, normalized-age, mortality-rate, and maximum-lifespan analyses. Displayed associations meet an FDR-adjusted P value threshold of 0.05. ITP is represented as a mouse cohort.</p></div></div>
        <div class="method-step" id="method-proteomics"><div class="method-step-content"><h3>Proteomics</h3><p>OrganAge records identify unambiguous single-gene SomaScan targets selected by the published organ-specific age models. The atlas reports organ assignment and selection frequency across 500 bootstrap models; organ-independent and cognition-optimized models are not treated as organ-specific evidence.</p></div></div>
        <div class="method-step planned"><div class="method-step-content"><h3>Metabolomics</h3><p>Coming next.</p></div></div>
        <div class="method-step planned"><div class="method-step-content"><h3>Integrative</h3><p>IMM-AGE · coming next.</p></div></div>
      </div>
    </section>
    <section class="section-block prose-section" id="interpretation">
      <h2>Interpretation</h2>
      <p>No universal evidence score or causal rank is assigned. Effects, P values, model-selection frequencies, cohort context, and curation status must be interpreted within the design of their source.</p>
    </section>`;
  setSectionNav([
    { id: "overview", label: "All evidence" },
    { id: "method-genomics", label: "Genomics" },
    { id: "method-epigenomics", label: "Epigenomics" },
    { id: "method-transcriptomics", label: "Transcriptomics" },
    { id: "method-proteomics", label: "Proteomics" },
    { label: "Metabolomics", note: "Coming next", disabled: true },
    { label: "Integrative", note: "IMM-AGE · coming next", disabled: true },
  ], "Evidence layers");
}

function renderSources() {
  const grouped = Object.fromEntries(ACTIVE_LAYER_KEYS.map((key) => [key, []]));
  state.sources.forEach((source) => grouped[source.layerKey]?.push(source));
  main.innerHTML = `
    ${pageHeader(
      "Sources",
      "Public evidence collections",
      "Source collections are nested under their omics layer, and each gene record links back to its originating study or resource.",
    )}
    <div id="source-collections">
      ${ACTIVE_LAYER_KEYS.map((key) => `
        <section class="source-layer-group ${escapeHtml(key)}" id="sources-${escapeHtml(key)}">
          <p class="section-kicker">Evidence layer</p>
          <h2>${escapeHtml(LAYER_DEFINITIONS[key].label)}</h2>
          ${grouped[key].map((source) => `
            <article class="source-entry ${escapeHtml(source.key)}">
              <div>
                <p class="source-organisms">${escapeHtml(source.organisms.join(" · "))}</p>
                <h3>${escapeHtml(source.title)}</h3>
                <p>${escapeHtml(source.description)}</p>
              </div>
              <a class="source-link" href="${escapeHtml(source.sourceUrl)}" target="_blank" rel="noreferrer">Open source</a>
            </article>`).join("")}
        </section>`).join("")}
      <section class="source-layer-group planned-sources" id="sources-metabolomics">
        <p class="section-kicker">Evidence layer</p>
        <h2>Metabolomics <span class="planned-status">Coming next</span></h2>
      </section>
      <section class="source-layer-group planned-sources" id="sources-integrative">
        <p class="section-kicker">Evidence layer</p>
        <h2>Integrative <span class="planned-status"><a href="https://doi.org/10.1038/s41591-019-0381-y" target="_blank" rel="noreferrer">IMM-AGE</a> · coming next</span></h2>
      </section>
    </div>`;
  setSectionNav([
    { id: "overview", label: "All evidence" },
    { id: "sources-genomics", label: "Genomics" },
    { id: "sources-epigenomics", label: "Epigenomics" },
    { id: "sources-transcriptomics", label: "Transcriptomics" },
    { id: "sources-proteomics", label: "Proteomics" },
    { label: "Metabolomics", note: "Coming next", disabled: true },
    { label: "Integrative", note: "IMM-AGE · coming next", disabled: true },
  ], "Evidence layers");
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
  else if (route === "genes") window.location.hash = "#/";
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
    document.querySelector("[data-focus-search]")?.addEventListener("click", () => {
      window.setTimeout(() => document.querySelector("#atlas-query")?.focus(), 0);
    });
  } catch (error) {
    main.innerHTML = `<div class="error-state"><h1>Atlas data could not be loaded</h1><p>${escapeHtml(error.message)}</p></div>`;
  }
}

window.addEventListener("hashchange", renderRoute);
initialize();

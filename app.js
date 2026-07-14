const DATA_ROOT = "data";

const state = {
  manifest: null,
  searchIndex: [],
  datasets: [],
  buildReport: null,
  chunks: new Map(),
  browseLimit: 60,
};

const main = document.querySelector("#main-content");
const sectionNav = document.querySelector("#section-nav");

const SOURCE_LABELS = {
  tAge: "tAge",
  cAge: "cAge",
  bAge: "bAge",
  integrative: "Integrative",
  longevity: "LongevityMap",
  genAge: "GenAge",
};

const SOURCE_CLASSES = {
  tAge: "tage",
  cAge: "cage",
  bAge: "bage",
  integrative: "integrative",
  longevity: "longevity",
  genAge: "genage",
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
        `<span class="source-mark ${SOURCE_CLASSES[source] || ""}">${escapeHtml(SOURCE_LABELS[source] || source)}</span>`,
    )
    .join("");
}

function setSectionNav(items) {
  sectionNav.innerHTML = items
    .map((item) => `<a href="#${escapeHtml(item.id)}">${escapeHtml(item.label)}</a>`)
    .join("");
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
      const name = (gene.name || "").toUpperCase();
      if (symbol.startsWith(query)) prefix.push(gene);
      else if (symbol.includes(query) || name.includes(query)) partial.push(gene);
      if (prefix.length + partial.length >= 12) break;
    }
    const matches = [...prefix, ...partial].slice(0, 10);
    results.innerHTML = matches.length
      ? matches
          .map(
            (gene) => `
              <a class="search-result" href="#/gene/${encodeURIComponent(gene.symbol)}">
                <strong>${escapeHtml(gene.symbol)}</strong>
                <span>${escapeHtml(gene.name || "Approved HGNC gene")}</span>
                <small>${escapeHtml(gene.location || "")}</small>
              </a>`,
          )
          .join("")
      : `<div class="search-result"><strong>No match</strong><span>Try a symbol or approved gene name.</span><small></small></div>`;
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
        <span class="rank-label">Atlas rank ${gene.rank}</span>
      </div>
      <div class="gene-card-name">${escapeHtml(gene.name || "Approved HGNC gene")}</div>
      <div class="source-marks">${sourceMarks(gene.sources)}</div>
    </a>`;
}

function renderHome() {
  const featured = state.manifest.featuredGenes
    .map((symbol) => state.searchIndex.find((gene) => gene.symbol === symbol))
    .filter(Boolean);
  const modules = state.datasets.filter((dataset) => Object.hasOwn(SOURCE_LABELS, dataset.id));

  main.innerHTML = `
    ${pageHeader(
      "Open evidence reference",
      "Aging Evidence Atlas",
      "Search gene-level evidence curated in Dr. Mahdi's consolidated workbook across transcriptomic age, epigenetic age and mortality, integrative, longevity, and GenAge modules.",
    )}

    <section class="search-panel" aria-label="Gene search">
      <label class="search-label" for="home-gene-search">Search by approved symbol or gene name</label>
      <div class="search-row">
        <input id="home-gene-search" type="search" autocomplete="off" placeholder="Examples: FOXO3, IGF1R, insulin receptor" />
        <button class="primary-button" id="home-search-button" type="button">Open gene record</button>
      </div>
      <div class="search-results" id="home-search-results" role="listbox"></div>
    </section>

    <div class="caution-note">
      The atlas follows the workbook's final Include decisions where an Include field is present. Evidence modules remain separate and are not converted into a causal, clinical, or biological-importance score.
    </div>

    <section class="section-block" id="evidence-landscape">
      <div class="section-heading-row">
        <h2>Evidence landscape</h2>
        <p>Workbook modules connected at the approved gene symbol</p>
      </div>
      <div class="evidence-map">
        <div class="constellation" role="img" aria-label="Six workbook modules connected through gene-level records">
          <div class="constellation-center"><strong>Gene-level</strong><span>evidence</span></div>
          <span class="orbit-node one"></span><span class="orbit-node gold two"></span>
          <span class="orbit-node navy three"></span><span class="orbit-node four"></span>
          <span class="orbit-node gold five"></span><span class="orbit-node navy six"></span>
        </div>
        <div class="collection-list">
          ${modules
            .map(
              (dataset) => `
                <div class="collection-item">
                  <span class="collection-dot"></span>
                  <div><strong>${escapeHtml(dataset.shortName)}</strong><p>${escapeHtml(dataset.scope)}</p></div>
                  <span class="collection-count">${["tAge", "longevity", "genAge"].includes(dataset.id) ? "Include = 1" : "All rows"}</span>
                </div>`,
            )
            .join("")}
        </div>
      </div>
    </section>

    <section class="section-block" id="featured-genes">
      <div class="section-heading-row">
        <h2>Broad-evidence genes</h2>
        <p>Widest module coverage under the workbook's final inclusion rules</p>
      </div>
      <div class="gene-grid">${featured.map(homeGeneCard).join("")}</div>
    </section>

    <section class="section-block" id="coverage">
      <div class="section-heading-row"><h2>How to read a record</h2></div>
      <div class="profile-grid">
        <div class="profile-component"><span class="profile-label">Breadth</span><span class="profile-value">Module coverage</span><p>Which workbook modules contain a retained, gene-mapped record.</p></div>
        <div class="profile-component"><span class="profile-label">Replication</span><span class="profile-value">Source rows</span><p>Analytes or association reports retained for the gene, interpreted within each source design.</p></div>
        <div class="profile-component"><span class="profile-label">Strength</span><span class="profile-value">Source statistics</span><p>Adjusted P values, P values, effects, and correlations remain in their native units.</p></div>
        <div class="profile-component"><span class="profile-label">Selection</span><span class="profile-value">Final Include</span><p>GenAge, LongevityMap, and tAge obey Dr. Mahdi's row-level inclusion decisions.</p></div>
        <div class="profile-component"><span class="profile-label">Convergence</span><span class="profile-value">Integrative evidence</span><p>Transcriptomic-epigenetic links are shown as a distinct module, not extra score points.</p></div>
      </div>
    </section>`;

  setSectionNav([
    { id: "overview", label: "Overview" },
    { id: "evidence-landscape", label: "Evidence landscape" },
    { id: "featured-genes", label: "Broad-evidence genes" },
    { id: "coverage", label: "Reading records" },
  ]);
  initializeSearch(main.querySelector(".search-panel"), "#home-gene-search", "#home-search-results", "#home-search-button");
}

function renderBrowseRows(genes) {
  return genes
    .map(
      (gene) => `
        <tr>
          <td class="numeric">${gene.rank}</td>
          <td><a class="gene-link" href="#/gene/${encodeURIComponent(gene.symbol)}">${escapeHtml(gene.symbol)}</a><br><small>${escapeHtml(gene.name || "")}</small></td>
          <td>${escapeHtml(gene.location || "Not reported")}</td>
          <td><div class="source-marks">${sourceMarks(gene.sources)}</div></td>
          <td class="numeric">${gene.supportingRecords}</td>
          <td class="numeric">${gene.tAgeRecords}</td>
          <td class="numeric">${gene.cAgeRecords}</td>
          <td class="numeric">${gene.bAgeRecords}</td>
          <td class="numeric">${gene.integrativeRecords}</td>
        </tr>`,
    )
    .join("");
}

function renderGenes() {
  const breadthOptions = [];
  for (let breadth = state.manifest.maximumBreadth; breadth >= 2; breadth -= 1) {
    breadthOptions.push(`<option value="${breadth}">${breadth} or more modules</option>`);
  }
  main.innerHTML = `
    ${pageHeader(
      "Gene index",
      "Gene evidence index",
      "The default order prioritizes module breadth, curated support, integrative convergence, supporting records, and source statistical support. It is a browsing hierarchy, not a biological importance score.",
    )}
    <div class="filter-bar" id="gene-filters">
      <div class="filter-control"><label for="browse-search">Symbol or approved name</label><input id="browse-search" type="search" placeholder="Search the index" /></div>
      <div class="filter-control"><label for="source-filter">Required module</label><select id="source-filter"><option value="">All modules</option>${Object.entries(SOURCE_LABELS).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></div>
      <div class="filter-control"><label for="breadth-filter">Evidence breadth</label><select id="breadth-filter"><option value="">Any breadth</option>${breadthOptions.join("")}</select></div>
    </div>
    <p class="result-summary" id="gene-result-summary"></p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>Rank</th><th>Gene</th><th>Human locus</th><th>Available modules</th><th>Supporting records</th><th>tAge</th><th>cAge</th><th>bAge</th><th>Integrative</th></tr></thead>
        <tbody id="gene-index-body"></tbody>
      </table>
    </div>
    <div class="pagination-row"><button class="secondary-button" id="show-more-genes" type="button">Show more genes</button></div>
    <div class="source-note section-block" id="index-note">Gene names and loci use approved HGNC human annotations. Source labels are retained only when they map to an approved HGNC symbol or a single unambiguous HGNC alias; this label harmonization does not itself infer orthology.</div>`;

  setSectionNav([
    { id: "overview", label: "Gene index" },
    { id: "gene-filters", label: "Search and filter" },
    { id: "index-note", label: "Harmonization note" },
  ]);

  const search = main.querySelector("#browse-search");
  const source = main.querySelector("#source-filter");
  const breadth = main.querySelector("#breadth-filter");
  const body = main.querySelector("#gene-index-body");
  const summary = main.querySelector("#gene-result-summary");
  const more = main.querySelector("#show-more-genes");

  const update = () => {
    const query = search.value.trim().toUpperCase();
    const requiredSource = source.value;
    const minimumBreadth = Number(breadth.value || 0);
    const filtered = state.searchIndex.filter((gene) => {
      const matchesQuery = !query || gene.symbol.includes(query) || (gene.name || "").toUpperCase().includes(query);
      const matchesSource = !requiredSource || gene.sources.includes(requiredSource);
      const matchesBreadth = !minimumBreadth || gene.sourceBreadth >= minimumBreadth;
      return matchesQuery && matchesSource && matchesBreadth;
    });
    const visible = filtered.slice(0, state.browseLimit);
    body.innerHTML = renderBrowseRows(visible);
    const filtersActive = Boolean(query || requiredSource || minimumBreadth);
    summary.textContent = filtersActive
      ? `Showing ${formatInteger(visible.length)} matching gene record${visible.length === 1 ? "" : "s"}.`
      : `Showing the first ${formatInteger(visible.length)} ranked gene records.`;
    more.hidden = visible.length >= filtered.length;
  };

  [search, source, breadth].forEach((control) =>
    control.addEventListener(control.tagName === "INPUT" ? "input" : "change", () => {
      state.browseLimit = 60;
      update();
    }),
  );
  more.addEventListener("click", () => {
    state.browseLimit += 100;
    update();
  });
  update();
}

function modalityPanel(title, count, text) {
  return `<article class="modality-panel"><h3>${escapeHtml(title)}</h3><div class="modality-count">${formatInteger(count)}</div><p>${escapeHtml(text)}</p></article>`;
}

function tAgeRows(records) {
  return records
    .map(
      (record) => `
        <tr><td>${formatNumber(record.slope, 6)}</td><td>${escapeHtml(record.direction)}</td><td>${formatNumber(record.standardError, 6)}</td><td>${formatNumber(record.pearsonCorrelation, 5)}</td><td>${formatProbability(record.pValue)}</td><td>${formatProbability(record.adjustedPValue)}</td></tr>`,
    )
    .join("");
}

function cAgeRows(records) {
  return records
    .map(
      (record) => `
        <tr><td>${escapeHtml(record.cpg)}</td><td>chr${escapeHtml(record.cpgChromosome)}:${escapeHtml(record.cpgPosition)}</td><td>${formatNumber(record.beta, 5)}</td><td>${formatNumber(record.standardError, 5)}</td><td>${formatProbability(record.pValue)}</td></tr>`,
    )
    .join("");
}

function bAgeRows(records) {
  return records
    .map(
      (record) => `
        <tr><td>${escapeHtml(record.cpg)}</td><td>chr${escapeHtml(record.cpgChromosome)}:${escapeHtml(record.cpgPosition)}</td><td>${formatNumber(record.logHazardRatio, 5)}</td><td>${formatNumber(record.hazardRatio, 4)}</td><td>${formatNumber(record.hazardRatioCiLow, 4)}–${formatNumber(record.hazardRatioCiHigh, 4)}</td><td>${formatProbability(record.pValue)}</td></tr>`,
    )
    .join("");
}

function integrativeRows(records) {
  return records
    .map(
      (record) => `
        <tr><td>${escapeHtml(record.cpg)}</td><td>chr${escapeHtml(record.cpgChromosome)}:${escapeHtml(record.cpgPositionHg38)}</td><td>${formatNumber(record.distanceToTss, 0)}</td><td>${formatNumber(record.ageCorrelation, 4)}</td></tr>`,
    )
    .join("");
}

function longevityRows(records) {
  return records
    .map(
      (record) => `
        <tr><td>${escapeHtml(record.population || "Not reported")}</td><td>${escapeHtml(record.variants || "Not reported")}</td><td>${record.pubmedUrl ? `<a href="${escapeHtml(record.pubmedUrl)}" target="_blank" rel="noreferrer">${escapeHtml(record.pubmedId)}</a>` : "Not reported"}</td><td>${record.sourceLink ? `<a href="${escapeHtml(record.sourceLink)}" target="_blank" rel="noreferrer">LongevityMap</a>` : "Not reported"}</td></tr>`,
    )
    .join("");
}

function tableOrEmpty(records, header, rows, emptyText) {
  if (!records.length) return `<div class="empty-evidence">${escapeHtml(emptyText)}</div>`;
  return `<div class="table-wrap"><table class="data-table"><thead>${header}</thead><tbody>${rows(records)}</tbody></table></div>`;
}

function bestStatisticalSupport(stats) {
  if (stats.bestTAgeAdjustedP) return `<span class="profile-stat-source">tAge adjusted P</span><span class="profile-stat-value">${formatProbability(stats.bestTAgeAdjustedP)}</span>`;
  if (stats.bestCAgeP) return `<span class="profile-stat-source">cAge P value</span><span class="profile-stat-value">${formatProbability(stats.bestCAgeP)}</span>`;
  if (stats.bestBAgeP) return `<span class="profile-stat-source">bAge P value</span><span class="profile-stat-value">${formatProbability(stats.bestBAgeP)}</span>`;
  return `<span class="profile-stat-value">Descriptive evidence</span>`;
}

async function renderGene(symbol) {
  main.innerHTML = `<div class="loading-state"><div class="loading-line"></div><div class="loading-line short"></div><p>Loading ${escapeHtml(symbol)} evidence...</p></div>`;
  const gene = await loadGene(symbol);
  if (!gene) {
    main.innerHTML = `${pageHeader("Gene record", "Gene not found", "The requested symbol is not in the current release.")}<p><a href="#/genes">Return to the gene index</a></p>`;
    setSectionNav([{ id: "overview", label: "Not found" }]);
    return;
  }

  const a = gene.annotation;
  const s = gene.statistics;
  const p = gene.evidenceProfile;
  const genAge = gene.genAgeRecord;
  const curatedLabel = p.curatedCollectionsAvailable.length
    ? p.curatedCollectionsAvailable.map((source) => SOURCE_LABELS[source]).join(" + ")
    : "No curated module";
  const genAgeBlock = genAge
    ? `<div class="curation-block"><h3>GenAge included entry</h3><p><strong>Selection basis:</strong> ${escapeHtml(genAge.selectionBasisRaw || "Not reported")}</p><p><strong>Supporting references:</strong> ${escapeHtml(genAge.supportingReferenceCount ?? "Not reported")} &nbsp; <strong>UniProt:</strong> ${escapeHtml(genAge.uniprotEntry || "Not reported")}</p><p>${genAge.pubmedUrl ? `<a href="${escapeHtml(genAge.pubmedUrl)}" target="_blank" rel="noreferrer">Open supporting PubMed record</a> · ` : ""}<a href="https://genomics.senescence.info/genes/entry.php?hgnc=${encodeURIComponent(gene.symbol)}" target="_blank" rel="noreferrer">Open GenAge</a></p></div>`
    : `<div class="empty-evidence">No GenAge record with final Include = 1 is mapped to this gene.</div>`;

  main.innerHTML = `
    <header class="page-header" id="overview">
      <p class="eyebrow">Gene record · Atlas rank ${gene.rank}</p>
      <div class="gene-title-line"><h1>${escapeHtml(gene.symbol)}</h1><div class="source-marks">${sourceMarks(p.sourceCollectionsAvailable)}</div></div>
      <p class="gene-approved-name">${escapeHtml(a.approvedName || "Approved HGNC gene")}</p>
    </header>

    <div class="gene-identity">
      <div class="gene-summary">
        ${gene.summary ? `<p>${escapeHtml(gene.summary)}</p><p><small>Functional summary: <a href="${escapeHtml(gene.summarySource.url)}" target="_blank" rel="noreferrer">NCBI Gene ${escapeHtml(gene.summarySource.humanEntrezId)}</a>.</small></p>` : `<p>No NCBI functional summary was available for this approved symbol. The workbook evidence below remains source-backed.</p>`}
        <div class="caution-note">Effect direction and magnitude are source-specific. They should not be interpreted as causal or uniformly beneficial or harmful.</div>
      </div>
      <dl class="gene-meta">
        <div><dt>Human locus</dt><dd>${escapeHtml(a.chromosomeLocation || "Not reported")}</dd></div>
        <div><dt>HGNC</dt><dd><a href="${escapeHtml(a.hgncUrl)}" target="_blank" rel="noreferrer">${escapeHtml(a.hgncId)}</a></dd></div>
        <div><dt>NCBI Gene</dt><dd>${a.ncbiUrl ? `<a href="${escapeHtml(a.ncbiUrl)}" target="_blank" rel="noreferrer">${escapeHtml(a.humanEntrezId)}</a>` : "Not reported"}</dd></div>
        <div><dt>Ensembl</dt><dd>${escapeHtml(a.ensemblGeneId || "Not reported")}</dd></div>
        <div><dt>Locus type</dt><dd>${escapeHtml(a.locusType || "Not reported")}</dd></div>
      </dl>
    </div>

    <section class="section-block" id="evidence-profile">
      <div class="section-heading-row"><h2>Evidence profile</h2><p>Components shown separately; no weighted total</p></div>
      <div class="profile-grid">
        <div class="profile-component"><span class="profile-label">Breadth</span><span class="profile-value">${p.sourceBreadth} modules</span><p>Workbook modules containing a retained, gene-mapped record.</p></div>
        <div class="profile-component"><span class="profile-label">Repeated support</span><span class="profile-value">${formatInteger(p.supportingRecords)} records</span><p>Retained source rows attached to this gene.</p></div>
        <div class="profile-component"><span class="profile-label">Statistical support</span><span class="profile-value">${bestStatisticalSupport(s)}</span><p>Strongest available source statistic, retained in its native scale.</p></div>
        <div class="profile-component"><span class="profile-label">Curation</span><span class="profile-value">${escapeHtml(curatedLabel)}</span><p>Final included evidence from the curated GenAge and LongevityMap sheets.</p></div>
        <div class="profile-component"><span class="profile-label">Convergence</span><span class="profile-value">${s.integrativeRecords ? `${formatInteger(s.integrativeRecords)} linked CpGs` : "Not represented"}</span><p>Records in the Integrative transcriptomic-epigenetic module.</p></div>
      </div>
    </section>

    <section class="section-block" id="evidence-overview">
      <div class="section-heading-row"><h2>Evidence overview</h2></div>
      <div class="modality-grid">
        ${modalityPanel("tAge", s.tAgeRecords, `${s.tAgePositive} positive and ${s.tAgeNegative} negative included transcriptomic associations.`)}
        ${modalityPanel("cAge", s.cAgeRecords, `${s.cAgeCpGs} chronological-age CpG associations.`)}
        ${modalityPanel("bAge", s.bAgeRecords, `${s.bAgeCpGs} mortality-associated CpGs.`)}
        ${modalityPanel("Integrative", s.integrativeRecords, `${s.integrativeCpGs} transcriptomic-epigenetic CpG links.`)}
        ${modalityPanel("LongevityMap", s.longevityRecords, "Significant, single-gene reports with final Include = 1.")}
        ${modalityPanel("GenAge", s.genAgeRecords, genAge ? `Included curated basis: ${genAge.selectionBasisRaw || "not reported"}.` : "No final included GenAge entry.")}
      </div>
    </section>

    <section class="section-block" id="tage">
      <div class="section-heading-row"><h2>tAge transcriptomic evidence</h2><p>Final Include = 1; adjusted P &lt; 0.01</p></div>
      ${tableOrEmpty(gene.tAgeRecords, "<tr><th>Slope</th><th>Direction</th><th>SE</th><th>Pearson correlation</th><th>P value</th><th>Adjusted P</th></tr>", tAgeRows, "No included tAge record is mapped to this gene.")}
      <p class="source-note">The workbook reports a mouse-ortholog Entrez identifier. The human identifier in the header comes independently from HGNC and NCBI.</p>
    </section>

    <section class="section-block" id="cage">
      <div class="section-heading-row"><h2>cAge epigenetic evidence</h2><p>Chronological-age CpG associations</p></div>
      ${tableOrEmpty(gene.cAgeRecords, "<tr><th>CpG</th><th>CpG coordinate</th><th>Beta</th><th>SE</th><th>P value</th></tr>", cAgeRows, "No gene-mapped cAge record is available.")}
      <p class="source-note">Coordinates locate CpG probes, not the gene locus in the record header.</p>
    </section>

    <section class="section-block" id="bage">
      <div class="section-heading-row"><h2>bAge mortality evidence</h2><p>All-cause mortality CpG associations</p></div>
      ${tableOrEmpty(gene.bAgeRecords, "<tr><th>CpG</th><th>CpG coordinate</th><th>logHR</th><th>HR</th><th>95% CI</th><th>P value</th></tr>", bAgeRows, "No gene-mapped bAge record is available.")}
      <p class="source-note">Hazard ratios are source associations and do not establish causality.</p>
    </section>

    <section class="section-block" id="integrative">
      <div class="section-heading-row"><h2>Integrative evidence</h2><p>Transcriptomic-epigenetic links</p></div>
      ${tableOrEmpty(gene.integrativeRecords, "<tr><th>CpG</th><th>hg38 coordinate</th><th>Distance to TSS</th><th>Age correlation</th></tr>", integrativeRows, "No Integrative sheet record is mapped to this gene.")}
    </section>

    <section class="section-block" id="longevity">
      <div class="section-heading-row"><h2>LongevityMap evidence</h2><p>Final Include = 1 only</p></div>
      ${tableOrEmpty(gene.longevityRecords, "<tr><th>Population</th><th>Variant(s)</th><th>PubMed</th><th>Source</th></tr>", longevityRows, "No final included LongevityMap record is mapped to this gene.")}
    </section>

    <section class="section-block" id="curation">
      <div class="section-heading-row"><h2>GenAge curated evidence</h2><p>Final Include = 1 only</p></div>
      ${genAgeBlock}
    </section>

    <section class="section-block" id="provenance">
      <div class="section-heading-row"><h2>Record provenance</h2></div>
      <p>Every record retains the consolidated workbook filename, sheet, row number, and inclusion basis in the published JSON. <a href="#/sources">Review source dimensions and inclusion rules</a>.</p>
      <p class="definition-note">${escapeHtml(gene.selectionNote)}</p>
    </section>`;

  setSectionNav([
    { id: "overview", label: gene.symbol },
    { id: "evidence-profile", label: "Evidence profile" },
    { id: "evidence-overview", label: "Overview" },
    { id: "tage", label: "tAge" },
    { id: "cage", label: "cAge" },
    { id: "bage", label: "bAge" },
    { id: "integrative", label: "Integrative" },
    { id: "longevity", label: "LongevityMap" },
    { id: "curation", label: "GenAge" },
    { id: "provenance", label: "Provenance" },
  ]);
}

function renderMethods() {
  main.innerHTML = `
    ${pageHeader(
      "Methods",
      "Workbook inclusion and evidence integration",
      "The consolidated workbook is authoritative. Its final Include values are applied wherever present, while source-specific statistics and units remain separate.",
    )}
    <section class="section-block" id="pipeline">
      <div class="section-heading-row"><h2>Data pipeline</h2></div>
      <div class="method-steps">
        <div class="method-step"><div><h3>Authoritative workbook</h3><p>The consolidated workbook is read without modification. Its checksum, sheet names, dimensions, and row-level provenance are recorded in the build report.</p></div></div>
        <div class="method-step"><div><h3>Final inclusion decisions</h3><p>tAge, LongevityMap, and GenAge require Include = 1. tAge's formula is adjusted P &lt; 0.01. LongevityMap requires all three supplied helper flags. GenAge uses the supplied final decision directly.</p></div></div>
        <div class="method-step"><div><h3>Modules without Include</h3><p>All populated cAge, bAge, and Integrative rows are retained. Because this is a gene atlas, cAge and bAge rows appear on gene pages only when the Gene annotation maps unambiguously.</p></div></div>
        <div class="method-step"><div><h3>Symbol harmonization</h3><p>Labels are retained only when they map to an approved HGNC symbol or one unambiguous previous or alias symbol. Ambiguous and unmapped labels are reported but not guessed.</p></div></div>
        <div class="method-step"><div><h3>Human annotation</h3><p>Approved names and cytogenetic locations use HGNC. NCBI summaries are attached only after both the human Entrez ID and approved symbol agree.</p></div></div>
        <div class="method-step"><div><h3>Browsing hierarchy</h3><p>Genes are ordered by module breadth, curated-module breadth, integrative convergence, supporting records, and source statistical support. No universal weighted score is calculated.</p></div></div>
        <div class="method-step"><div><h3>Independent reconciliation</h3><p>A separate audit traces every published record to the workbook sheet and row, verifies Include values and statistics, checks the ranking order, and verifies source hashes.</p></div></div>
      </div>
    </section>
    <section class="section-block" id="evidence-components">
      <div class="section-heading-row"><h2>Evidence components</h2></div>
      <div class="profile-grid">
        <div class="profile-component"><span class="profile-label">Breadth</span><span class="profile-value">Module coverage</span><p>Distinct workbook modules represented.</p></div>
        <div class="profile-component"><span class="profile-label">Repeated support</span><span class="profile-value">Source records</span><p>Retained analytes and reports attached to the gene.</p></div>
        <div class="profile-component"><span class="profile-label">Strength</span><span class="profile-value">Native statistics</span><p>P values, adjusted P values, effects, correlations, and hazard ratios remain separate.</p></div>
        <div class="profile-component"><span class="profile-label">Selection</span><span class="profile-value">Final Include</span><p>Workbook decisions for tAge, LongevityMap, and GenAge.</p></div>
        <div class="profile-component"><span class="profile-label">Convergence</span><span class="profile-value">Integrative links</span><p>Cross-omic CpG-gene records shown without score inflation.</p></div>
      </div>
    </section>
    <section class="section-block" id="quality-notes">
      <div class="section-heading-row"><h2>Workbook quality notes</h2></div>
      <ul>${state.buildReport.qualityNotes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>
    </section>
    <section class="section-block" id="interpretation">
      <div class="section-heading-row"><h2>Interpretation limits</h2></div>
      <div class="caution-note">Inclusion means the record satisfies the workbook rule. It does not establish causality, clinical actionability, or uniform benefit or harm.</div>
      <ul>
        <li>tAge slope direction is specific to the source model and chronological-age endpoint.</li>
        <li>CpG coordinates in cAge, bAge, and Integrative locate probes, not gene bodies.</li>
        <li>LongevityMap entries are significant single-gene reports after final workbook filtering; repeated rows may represent different populations or variants.</li>
        <li>No standalone proteomic dataset is present in the consolidated workbook, so proteomic evidence is not claimed.</li>
      </ul>
    </section>`;

  setSectionNav([
    { id: "overview", label: "Methods overview" },
    { id: "pipeline", label: "Data pipeline" },
    { id: "evidence-components", label: "Evidence components" },
    { id: "quality-notes", label: "Quality notes" },
    { id: "interpretation", label: "Interpretation limits" },
  ]);
}

function datasetFacts(dataset) {
  const report = dataset.report || {};
  if (dataset.id === "tAge") return [`${formatInteger(report.rows)} source rows`, `${formatInteger(report.includeFlaggedRows)} with Include = 1`, `${formatInteger(report.mappedIncludedRows)} HGNC-mapped included rows`];
  if (dataset.id === "cAge" || dataset.id === "bAge") return [`${formatInteger(report.rows)} source rows`, `${formatInteger(report.rowsWithGeneAnnotation)} gene-annotated rows`, `${formatInteger(report.mappedGeneAssignments)} mapped gene assignments`];
  if (dataset.id === "integrative") return [`${formatInteger(report.rows)} source rows`, `${formatInteger(report.mappedRows)} mapped rows`, `${formatInteger(report.mappedGenes)} mapped genes`];
  if (dataset.id === "longevity") return [`${formatInteger(report.rows)} source rows`, `${formatInteger(report.includeFlaggedRows)} with Include = 1`, `${formatInteger(report.mappedIncludedRows)} mapped included rows`];
  if (dataset.id === "genAge") return [`${formatInteger(report.rows)} source rows`, `${formatInteger(report.includeFlaggedRows)} with Include = 1`, `${formatInteger(report.mappedGenes)} mapped included genes`];
  if (dataset.id === "hgnc") return [`${formatInteger(report.approvedRecords)} approved records`, `${formatInteger(report.unambiguousAliases)} unambiguous aliases`];
  if (dataset.id === "ncbi") return ["Human Entrez IDs and approved symbols cross-checked", `${formatInteger(report.summariesAttached)} summaries attached`, `${report.symbolMismatchesExcluded?.length || 0} symbol mismatches`];
  return [];
}

function renderSources() {
  main.innerHTML = `
    ${pageHeader(
      "Sources and provenance",
      "Consolidated evidence modules",
      "Scientific evidence is read from Dr. Mahdi's consolidated workbook. HGNC and NCBI provide authoritative human gene annotations but are not counted as evidence modules.",
    )}
    <div class="definition-note">Build generated ${new Date(state.manifest.generatedAt).toLocaleString("en-US", { dateStyle: "long", timeStyle: "short" })}. Source checksums and row-level reconciliation results are published in the build report.</div>
    <section class="section-block" id="source-list">
      ${state.datasets
        .map(
          (dataset) => `
            <article class="source-entry" id="source-${escapeHtml(dataset.id)}">
              <div>
                <p class="eyebrow">${escapeHtml(dataset.shortName)}</p>
                <h2>${escapeHtml(dataset.name)}</h2>
                <p class="source-file">${escapeHtml(dataset.sourceFile)}${dataset.sourceSheet ? ` · ${escapeHtml(dataset.sourceSheet)}` : ""}</p>
                ${dataset.publicationUrl ? `<p><a href="${escapeHtml(dataset.publicationUrl)}" target="_blank" rel="noreferrer">Open authoritative source</a></p>` : ""}
              </div>
              <div>
                <p><strong>Scope:</strong> ${escapeHtml(dataset.scope)}</p>
                <p><strong>Atlas inclusion:</strong> ${escapeHtml(dataset.inclusionRule)}</p>
                <div class="source-facts">${datasetFacts(dataset).map((fact) => `<div class="source-fact">${escapeHtml(fact)}</div>`).join("")}</div>
              </div>
            </article>`,
        )
        .join("")}
    </section>
    <section class="section-block" id="quality-notes">
      <div class="section-heading-row"><h2>Recorded source discrepancies</h2></div>
      <ul>${state.buildReport.qualityNotes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>
    </section>
    <section class="section-block" id="release-scope">
      <div class="section-heading-row"><h2>Release scope</h2></div>
      <p>This demonstration publishes derived gene records and provenance, not the original workbook. The source workbook remains unchanged.</p>
      <p class="caution-note">No standalone proteomic dataset is included, so the atlas does not label genes as having proteomic support.</p>
    </section>`;

  setSectionNav([
    { id: "overview", label: "Source overview" },
    { id: "source-list", label: "Evidence modules" },
    { id: "quality-notes", label: "Quality notes" },
    { id: "release-scope", label: "Release scope" },
  ]);
}

async function renderRoute() {
  const route = routeFromHash();
  setActiveNav(route);
  window.scrollTo({ top: 0, behavior: "auto" });
  try {
    if (route === "home") renderHome();
    else if (route === "genes") renderGenes();
    else if (route === "methods") renderMethods();
    else if (route === "sources") renderSources();
    else if (route.startsWith("gene/")) await renderGene(decodeURIComponent(route.split("/")[1] || ""));
    else renderHome();
  } catch (error) {
    console.error(error);
    main.innerHTML = `<div class="error-state"><h1>Atlas data could not be displayed</h1><p>${escapeHtml(error.message)}</p><p>Reload the page or return to <a href="#/">the atlas home page</a>.</p></div>`;
    setSectionNav([{ id: "overview", label: "Error" }]);
  }
  main.focus({ preventScroll: true });
}

async function initialize() {
  try {
    [state.manifest, state.searchIndex, state.datasets, state.buildReport] = await Promise.all([
      fetchJson(`${DATA_ROOT}/manifest.json`),
      fetchJson(`${DATA_ROOT}/search-index.json`),
      fetchJson(`${DATA_ROOT}/datasets.json`),
      fetchJson(`${DATA_ROOT}/build-report.json`),
    ]);
    await renderRoute();
  } catch (error) {
    console.error(error);
    main.innerHTML = `<div class="error-state"><h1>Atlas data failed to load</h1><p>${escapeHtml(error.message)}</p><p>This site must be opened through a web server rather than directly from the filesystem.</p></div>`;
  }
}

window.addEventListener("hashchange", renderRoute);
initialize();

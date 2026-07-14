const DATA_ROOT = "data";

const state = {
  manifest: null,
  searchIndex: [],
  datasets: [],
  chunks: new Map(),
  browseLimit: 60,
};

const main = document.querySelector("#main-content");
const sectionNav = document.querySelector("#section-nav");

const SOURCE_LABELS = {
  transcriptomic: "Transcriptomic",
  epigenetic: "Epigenetic",
  longevity: "LongevityMap",
  genAge: "GenAge",
};

const SOURCE_CLASSES = {
  transcriptomic: "transcriptomic",
  epigenetic: "epigenetic",
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
  document.addEventListener(
    "click",
    (event) => {
      if (!panel.contains(event.target)) results.classList.remove("open");
    },
    { once: true },
  );
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
  const m = state.manifest;
  const featured = m.featuredGenes
    .map((symbol) => state.searchIndex.find((gene) => gene.symbol === symbol))
    .filter(Boolean);

  main.innerHTML = `
    ${pageHeader(
      "Open evidence reference",
      "Aging Evidence Atlas",
      "Search and compare gene-level evidence across transcriptomic ageing and mortality signatures, epigenetic associations, human longevity studies, and curated ageing-gene resources.",
    )}

    <section class="search-panel" aria-label="Gene search">
      <label class="search-label" for="home-gene-search">Search by approved symbol or gene name</label>
      <div class="search-row">
        <input id="home-gene-search" type="search" autocomplete="off" placeholder="Examples: FOXO3, CDKN1A, insulin receptor" />
        <button class="primary-button" id="home-search-button" type="button">Open gene record</button>
      </div>
      <div class="search-results" id="home-search-results" role="listbox"></div>
    </section>

    <div class="metric-strip" aria-label="Atlas summary">
      <div class="metric"><span class="metric-value">4</span><span class="metric-label">distinct evidence collections</span></div>
      <div class="metric"><span class="metric-value">${formatInteger(m.transcriptomicSignificantRecords)}</span><span class="metric-label">significant transcriptomic rows</span></div>
      <div class="metric"><span class="metric-value">${formatInteger(m.epigeneticGeneAssignments)}</span><span class="metric-label">gene-linked epigenetic assignments</span></div>
      <div class="metric"><span class="metric-value">${formatInteger(m.genAgeGenes)}</span><span class="metric-label">curated GenAge genes</span></div>
    </div>

    <div class="caution-note">
      This atlas summarizes association and curation evidence. It does not assign a causal, clinical, or biological-importance score.
    </div>

    <section class="section-block" id="evidence-landscape">
      <div class="section-heading-row">
        <h2>Evidence landscape</h2>
        <p>Four source collections, retained as distinct evidence types</p>
      </div>
      <div class="evidence-map">
        <div class="constellation" role="img" aria-label="Four evidence collections connected through gene-level records">
          <div class="constellation-center"><strong>Gene-level</strong><span>evidence</span></div>
          <span class="orbit-node one"></span><span class="orbit-node gold two"></span>
          <span class="orbit-node navy three"></span><span class="orbit-node four"></span>
          <span class="orbit-node gold five"></span><span class="orbit-node navy six"></span>
        </div>
        <div class="collection-list">
          <div class="collection-item"><span class="collection-dot"></span><div><strong>Transcriptomic signatures</strong><p>Age, mortality, normalized-age, and lifespan analyses across six biological scopes.</p></div><span class="collection-count">18 tables</span></div>
          <div class="collection-item"><span class="collection-dot"></span><div><strong>Epigenetic associations</strong><p>Gene-annotated CpGs from chronological-age and all-cause mortality EWAS tables.</p></div><span class="collection-count">4 tables</span></div>
          <div class="collection-item"><span class="collection-dot"></span><div><strong>LongevityMap</strong><p>Human genetic association reports, retaining significant and non-significant findings.</p></div><span class="collection-count">${formatInteger(m.longevityRows)} reports</span></div>
          <div class="collection-item"><span class="collection-dot"></span><div><strong>GenAge human genes</strong><p>Expert-curated candidate genes linked to ageing in human or model-system evidence.</p></div><span class="collection-count">${formatInteger(m.genAgeGenes)} genes</span></div>
        </div>
      </div>
    </section>

    <section class="section-block" id="featured-genes">
      <div class="section-heading-row">
        <h2>Broad-evidence genes</h2>
        <p>Featured because all four supplied collections contain mapped evidence</p>
      </div>
      <div class="gene-grid">${featured.map(homeGeneCard).join("")}</div>
    </section>

    <section class="section-block" id="coverage">
      <div class="section-heading-row"><h2>Coverage, not a universal score</h2></div>
      <p class="lede">Each record separates breadth, repeated support, statistical evidence, curation, and human relevance. Exact source rows remain available below every gene summary, allowing the evidence profile to be checked rather than accepted as a black-box rank.</p>
      <p><a href="#/methods">Read the ranking and harmonization methods</a></p>
    </section>`;

  setSectionNav([
    { id: "overview", label: "Overview" },
    { id: "evidence-landscape", label: "Evidence landscape" },
    { id: "featured-genes", label: "Broad-evidence genes" },
    { id: "coverage", label: "Coverage principles" },
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
          <td class="numeric">${gene.analysisUnits}</td>
          <td class="numeric">${gene.transcriptomicRecords}</td>
          <td class="numeric">${gene.epigeneticRecords}</td>
          <td class="numeric">${gene.longevitySignificant}</td>
        </tr>`,
    )
    .join("");
}

function renderGenes() {
  main.innerHTML = `
    ${pageHeader(
      "Gene index",
      "Gene evidence index",
      "The default order prioritizes evidence breadth and human relevance before record volume and statistical strength. It is a browsing hierarchy, not a biological importance score.",
    )}
    <div class="filter-bar" id="gene-filters">
      <div class="filter-control"><label for="browse-search">Symbol or approved name</label><input id="browse-search" type="search" placeholder="Search the index" /></div>
      <div class="filter-control"><label for="source-filter">Required source</label><select id="source-filter"><option value="">All sources</option><option value="transcriptomic">Transcriptomic</option><option value="epigenetic">Epigenetic</option><option value="longevity">LongevityMap</option><option value="genAge">GenAge</option></select></div>
      <div class="filter-control"><label for="breadth-filter">Evidence breadth</label><select id="breadth-filter"><option value="">Any breadth</option><option value="4">4 collections</option><option value="3">3 or more</option><option value="2">2 or more</option></select></div>
    </div>
    <p class="result-summary" id="gene-result-summary"></p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>Rank</th><th>Gene</th><th>Human locus</th><th>Available evidence</th><th>Analysis units</th><th>Transcript rows</th><th>Epigenetic rows</th><th>Significant longevity reports</th></tr></thead>
        <tbody id="gene-index-body"></tbody>
      </table>
    </div>
    <div class="pagination-row"><button class="secondary-button" id="show-more-genes" type="button">Show more genes</button></div>
    <div class="source-note section-block" id="index-note">Gene names and loci use approved HGNC human annotations. Cross-species source symbols are case-normalized and retained only when they match an approved HGNC symbol or an unambiguous HGNC alias; this label harmonization does not itself infer orthology.</div>`;

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

function directionChart(records) {
  const families = ["ITP", "Rodents", "Mouse", "Rat", "Macaque", "Human"];
  const rows = families
    .map((family) => {
      const subset = records.filter((record) => record.family === family);
      if (!subset.length) return "";
      const positive = subset.filter((record) => record.direction === "Positive").length;
      const negative = subset.filter((record) => record.direction === "Negative").length;
      const total = positive + negative || 1;
      return `
        <div class="direction-row">
          <strong>${escapeHtml(family)}</strong>
          <div class="direction-track" aria-label="${positive} positive and ${negative} negative transcriptomic associations">
            <span class="direction-positive" style="width:${(positive / total) * 100}%"></span>
            <span class="direction-negative" style="width:${(negative / total) * 100}%"></span>
          </div>
          <span>${positive} + / ${negative} -</span>
        </div>`;
    })
    .filter(Boolean)
    .join("");
  return rows || `<div class="empty-evidence">No significant transcriptomic records in the indexed source sheets.</div>`;
}

function transcriptRows(records) {
  return records
    .map(
      (record) => `
        <tr>
          <td>${escapeHtml(record.family)}</td>
          <td>${escapeHtml(record.endpoint)}</td>
          <td>${escapeHtml(record.model)}</td>
          <td>${escapeHtml(record.sourceSheet)}</td>
          <td class="numeric">${formatNumber(record.slope, 5)}</td>
          <td>${escapeHtml(record.direction)}</td>
          <td class="numeric">${formatProbability(record.adjustedPValue)}</td>
          <td class="numeric">${formatNumber(record.associationValue, 4)}</td>
        </tr>`,
    )
    .join("");
}

function epigeneticRows(records) {
  return records
    .map((record) => {
      const effect = record.hazardRatio ?? record.quadraticBeta ?? record.beta;
      const effectLabel = record.hazardRatio !== undefined ? "HR" : record.quadraticBeta !== undefined ? "Quadratic beta" : "Beta";
      return `
        <tr>
          <td>${escapeHtml(record.sourceSheet)}</td>
          <td>${escapeHtml(record.endpoint)}</td>
          <td>${escapeHtml(record.cpg)}</td>
          <td>${escapeHtml(record.cpgChromosome)}:${formatInteger(record.cpgPosition)}</td>
          <td>${effectLabel}</td>
          <td class="numeric">${formatNumber(effect, 5)}</td>
          <td class="numeric">${formatProbability(record.pValue)}</td>
        </tr>`;
    })
    .join("");
}

function longevityRows(records) {
  return records
    .map(
      (record) => `
        <tr>
          <td>${escapeHtml(record.association)}</td>
          <td>${escapeHtml(record.population || "Not reported")}</td>
          <td>${escapeHtml(record.variants || "Not reported")}</td>
          <td>${record.pubmedUrl ? `<a href="${escapeHtml(record.pubmedUrl)}" target="_blank" rel="noreferrer">${escapeHtml(record.pubmedId)}</a>` : "Not reported"}</td>
        </tr>`,
    )
    .join("");
}

function tableOrEmpty(records, header, rows, emptyText) {
  if (!records.length) return `<div class="empty-evidence">${escapeHtml(emptyText)}</div>`;
  return `<div class="table-wrap"><table class="data-table"><thead>${header}</thead><tbody>${rows(records)}</tbody></table></div>`;
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
  const transcriptP = s.bestTranscriptomicAdjustedP ? formatProbability(s.bestTranscriptomicAdjustedP) : "No indexed FDR record";
  const humanTypes = Object.entries(gene.humanEvidenceFlags)
    .filter(([, present]) => present)
    .map(([key]) => key)
    .length;
  const genAge = gene.genAgeRecord;
  const genAgeBlock = genAge
    ? `<div class="curation-block"><h3>GenAge curated entry</h3><p><strong>Selection basis:</strong> ${escapeHtml(genAge.selectionBasisRaw || "Not reported")}</p><p><strong>GenAge ID:</strong> ${escapeHtml(genAge.genAgeId)} &nbsp; <strong>UniProt entry:</strong> ${escapeHtml(genAge.uniprotEntry || "Not reported")}</p><p><a href="https://genomics.senescence.info/genes/entry.php?hgnc=${encodeURIComponent(gene.symbol)}" target="_blank" rel="noreferrer">Open the GenAge gene search</a></p></div>`
    : `<div class="empty-evidence">This gene is not present in the supplied 307-gene GenAge human file.</div>`;

  main.innerHTML = `
    <header class="page-header" id="overview">
      <p class="eyebrow">Gene record · Atlas rank ${gene.rank}</p>
      <div class="gene-title-line"><h1>${escapeHtml(gene.symbol)}</h1><div class="source-marks">${sourceMarks(p.sourceCollectionsAvailable)}</div></div>
      <p class="gene-approved-name">${escapeHtml(a.approvedName || "Approved HGNC gene")}</p>
    </header>

    <div class="gene-identity">
      <div class="gene-summary">
        ${gene.summary ? `<p>${escapeHtml(gene.summary)}</p><p><small>Functional summary: <a href="${escapeHtml(gene.summarySource.url)}" target="_blank" rel="noreferrer">NCBI Gene ${escapeHtml(gene.summarySource.humanEntrezId)}</a>.</small></p>` : `<p>No NCBI functional summary was available for this approved symbol. The evidence records below remain source-backed.</p>`}
        <div class="caution-note">Direction is the sign of the source association coefficient. Its biological meaning depends on the endpoint and model and should not be interpreted as causal or uniformly beneficial/harmful.</div>
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
        <div class="profile-component"><span class="profile-label">Breadth</span><span class="profile-value">${p.sourceBreadth} of 4</span><p>Supplied evidence collections containing a mapped record.</p></div>
        <div class="profile-component"><span class="profile-label">Repeated support</span><span class="profile-value">${formatInteger(p.analysisUnits)} units</span><p>Source tables, LongevityMap publications, and GenAge curation represented.</p></div>
        <div class="profile-component"><span class="profile-label">Statistical support</span><span class="profile-value">${transcriptP}</span><p>Best transcriptomic adjusted P value; epigenetic P values are reported separately below.</p></div>
        <div class="profile-component"><span class="profile-label">Curation</span><span class="profile-value">${p.curatedInGenAge ? "GenAge listed" : "Not listed"}</span><p>Status in the supplied GenAge human-gene file.</p></div>
        <div class="profile-component"><span class="profile-label">Human relevance</span><span class="profile-value">${humanTypes} of 4</span><p>Human transcriptomic, epigenetic, longevity-association, and human GenAge evidence types.</p></div>
      </div>
    </section>

    <section class="section-block" id="evidence-overview">
      <div class="section-heading-row"><h2>Evidence overview</h2></div>
      <div class="modality-grid">
        ${modalityPanel("Transcriptomic", s.transcriptomicRecords, `${p.transcriptomicTables} significant source analyses; ${s.transcriptomicPositive} positive and ${s.transcriptomicNegative} negative slopes.`)}
        ${modalityPanel("Epigenetic", s.epigeneticRecords, `${s.epigeneticCpGs} gene-annotated CpG loci across ${p.epigeneticTables} source tables.`)}
        ${modalityPanel("LongevityMap", s.longevityRecords, `${s.longevitySignificant} significant and ${s.longevityNonSignificant} non-significant association reports.`)}
        ${modalityPanel("GenAge", genAge ? 1 : 0, genAge ? `Curated selection basis: ${genAge.selectionBasisRaw || "not reported"}.` : "No entry in the supplied GenAge human file.")}
      </div>
    </section>

    <section class="section-block" id="transcriptomic">
      <div class="section-heading-row"><h2>Transcriptomic evidence</h2><p>FDR ≤ 0.05 records only</p></div>
      <div class="direction-chart">${directionChart(gene.transcriptomicRecords)}</div>
      ${tableOrEmpty(
        gene.transcriptomicRecords,
        "<tr><th>Scope</th><th>Endpoint</th><th>Model</th><th>Source table</th><th>Slope</th><th>Direction</th><th>Adjusted P</th><th>Correlation / LR</th></tr>",
        transcriptRows,
        "No significant transcriptomic records in the indexed source sheets.",
      )}
      <p class="source-note">The source workbook reports mouse-ortholog Entrez identifiers across these harmonized analyses. The human identifier in the gene header comes separately from HGNC/NCBI.</p>
    </section>

    <section class="section-block" id="epigenetic">
      <div class="section-heading-row"><h2>Epigenetic evidence</h2><p>Source Tables S1-S4</p></div>
      ${tableOrEmpty(
        gene.epigeneticRecords,
        "<tr><th>Table</th><th>Endpoint</th><th>CpG</th><th>CpG coordinate</th><th>Effect</th><th>Estimate</th><th>P value</th></tr>",
        epigeneticRows,
        "No gene-annotated CpG record for this gene in source Tables S1-S4.",
      )}
      <p class="source-note">Coordinates in this table refer to CpG loci, not the gene locus shown in the header. These source tables contain epigenome-wide significant associations (P &lt; 3.6 × 10<sup>-8</sup>).</p>
    </section>

    <section class="section-block" id="longevity">
      <div class="section-heading-row"><h2>Longevity association evidence</h2><p>Significant and non-significant reports retained</p></div>
      ${tableOrEmpty(
        gene.longevityRecords,
        "<tr><th>Study finding</th><th>Population</th><th>Variant(s)</th><th>PubMed</th></tr>",
        longevityRows,
        "No record for this gene in the supplied LongevityMap Build 3 file.",
      )}
    </section>

    <section class="section-block" id="curation">
      <div class="section-heading-row"><h2>Curated ageing-gene evidence</h2></div>
      ${genAgeBlock}
    </section>

    <section class="section-block" id="provenance">
      <div class="section-heading-row"><h2>Record provenance</h2></div>
      <p>Every row above retains its source filename, sheet, and row number in the published JSON data. <a href="#/sources">Review source files and inclusion rules</a>.</p>
      <p class="definition-note">${escapeHtml(gene.selectionNote)}</p>
    </section>`;

  setSectionNav([
    { id: "overview", label: gene.symbol },
    { id: "evidence-profile", label: "Evidence profile" },
    { id: "evidence-overview", label: "Overview" },
    { id: "transcriptomic", label: "Transcriptomic" },
    { id: "epigenetic", label: "Epigenetic" },
    { id: "longevity", label: "LongevityMap" },
    { id: "curation", label: "GenAge" },
    { id: "provenance", label: "Provenance" },
  ]);
}

function renderMethods() {
  main.innerHTML = `
    ${pageHeader(
      "Methods",
      "Evidence integration and ranking",
      "The atlas is designed for transparent evidence lookup. Source-specific statistics are preserved, and the browsing rank is constructed without a weighted biological score.",
    )}

    <section class="section-block" id="pipeline">
      <div class="section-heading-row"><h2>Data pipeline</h2></div>
      <div class="method-steps">
        <div class="method-step"><div><h3>Source preservation</h3><p>The four supplied files are read without modification. Their SHA-256 checksums, row counts, sheet names, and inclusion rules are recorded in the build report.</p></div></div>
        <div class="method-step"><div><h3>Symbol harmonization</h3><p>Symbols are uppercased for matching, then retained only when they map to an approved HGNC symbol or a single unambiguous HGNC previous/alias symbol. Ambiguous aliases are excluded. This label harmonization does not infer orthology.</p></div></div>
        <div class="method-step"><div><h3>Evidence inclusion</h3><p>Transcriptomic rows require Benjamini-Hochberg adjusted P ≤ 0.05. Epigenetic records come from source Tables S1-S4, whose titles specify epigenome-wide significance at P &lt; 3.6 × 10<sup>-8</sup>. All supplied GenAge and LongevityMap rows are retained; LongevityMap non-significant findings remain visible.</p></div></div>
        <div class="method-step"><div><h3>Human annotation</h3><p>Approved names and cytogenetic locations use the HGNC complete set. NCBI summaries are attached only after matching both the human Entrez ID and approved symbol.</p></div></div>
        <div class="method-step"><div><h3>Selection and rank</h3><p>Genes are ordered lexicographically by evidence breadth, human evidence types, GenAge curation, significant LongevityMap reports, analysis units, record count, and then statistical support. No components are multiplied or summed into a universal score.</p></div></div>
        <div class="method-step"><div><h3>Independent reconciliation</h3><p>A second validation pass traces each published record back to the original sheet and row, verifies identifiers and statistics, confirms the ranking order, and checks all source file hashes.</p></div></div>
      </div>
    </section>

    <section class="section-block" id="evidence-components">
      <div class="section-heading-row"><h2>Evidence components</h2></div>
      <div class="profile-grid">
        <div class="profile-component"><span class="profile-label">Breadth</span><span class="profile-value">Source coverage</span><p>Which supplied evidence collections contain the gene.</p></div>
        <div class="profile-component"><span class="profile-label">Repeated support</span><span class="profile-value">Analysis units</span><p>Tables, PubMed-indexed LongevityMap reports, and curation represented.</p></div>
        <div class="profile-component"><span class="profile-label">Strength</span><span class="profile-value">Exact P values</span><p>Adjusted transcriptomic P and source epigenetic P are shown, not converted to points.</p></div>
        <div class="profile-component"><span class="profile-label">Curation</span><span class="profile-value">GenAge status</span><p>Presence and supplied selection basis in the curated human-gene file.</p></div>
        <div class="profile-component"><span class="profile-label">Human relevance</span><span class="profile-value">Human evidence types</span><p>Human transcriptomic, epigenetic, longevity, and GenAge evidence available.</p></div>
      </div>
    </section>

    <section class="section-block" id="interpretation">
      <div class="section-heading-row"><h2>Interpretation limits</h2></div>
      <div class="caution-note">A high rank indicates broad coverage in the supplied sources. It does not mean that a gene is causal, clinically actionable, more important to ageing, or consistently beneficial or detrimental.</div>
      <ul>
        <li>Slopes and hazard ratios are endpoint- and model-specific; their signs are not interchangeable.</li>
        <li>Transcriptomic source identifiers are mouse-ortholog Entrez IDs as reported in the workbook, even for harmonized primate analyses.</li>
        <li>Epigenetic chromosome and position fields locate CpGs, not gene bodies.</li>
        <li>LongevityMap includes negative findings by design; multiple rows may refer to different populations or variants.</li>
        <li>This release contains transcriptomic, epigenetic, longevity-association, and curated gene evidence. No standalone proteomic dataset was supplied, so proteomic evidence is not claimed.</li>
      </ul>
    </section>`;

  setSectionNav([
    { id: "overview", label: "Methods overview" },
    { id: "pipeline", label: "Data pipeline" },
    { id: "evidence-components", label: "Evidence components" },
    { id: "interpretation", label: "Interpretation limits" },
  ]);
}

function datasetFacts(dataset) {
  const report = dataset.report || {};
  if (dataset.id === "transcriptomic") {
    return [
      `${formatInteger(report.rowsTested)} gene-analysis rows tested`,
      `${formatInteger(report.fdrSignificantRows)} FDR-significant rows`,
      `${formatInteger(report.geneCountWithMappedSignificantEvidence)} mapped genes`,
      `${report.sheets?.length || 0} source sheets`,
    ];
  }
  if (dataset.id === "epigenetic") {
    return [
      `${formatInteger(report.associationRows)} source associations`,
      `${formatInteger(report.rowsWithGeneAnnotation)} rows with gene annotation`,
      `${formatInteger(report.mappedGeneAssignments)} mapped gene assignments`,
      `${report.tables?.length || 0} indexed source tables`,
    ];
  }
  if (dataset.id === "genage") return [`${formatInteger(report.rows)} supplied rows`, `${formatInteger(report.mappedGenes)} HGNC-mapped genes`];
  if (dataset.id === "longevity") return [`${formatInteger(report.rows)} association reports`, `${formatInteger(report.mappedGenes)} HGNC-mapped genes`, `${formatInteger(report.associationCounts?.Significant)} significant reports`, `${formatInteger(report.associationCounts?.["Non-significant"])} non-significant reports`];
  if (dataset.id === "hgnc") return [`${formatInteger(report.approvedRecords)} approved records`, `${formatInteger(report.unambiguousAliases)} unambiguous aliases`];
  if (dataset.id === "ncbi") return ["Human Entrez IDs and approved symbols cross-checked", `${formatInteger(report.summariesAttached)} summaries attached`, `${report.symbolMismatchesExcluded?.length || 0} symbol mismatches`];
  return [];
}

function renderSources() {
  main.innerHTML = `
    ${pageHeader(
      "Sources and provenance",
      "Data collections in this release",
      "The atlas combines four supplied scientific evidence sources and two authoritative annotation references. Each source retains its own meaning, units, and inclusion rule.",
    )}
    <div class="definition-note">Build generated ${new Date(state.manifest.generatedAt).toLocaleString("en-US", { dateStyle: "long", timeStyle: "short" })}. Source-file checksums and row-level reconciliation results are published in the data build report.</div>
    <section class="section-block" id="source-list">
      ${state.datasets
        .map(
          (dataset) => `
            <article class="source-entry" id="source-${escapeHtml(dataset.id)}">
              <div>
                <p class="eyebrow">${escapeHtml(dataset.shortName)}</p>
                <h2>${escapeHtml(dataset.name)}</h2>
                <p class="source-file">${escapeHtml(dataset.sourceFile)}</p>
                <p><a href="${escapeHtml(dataset.publicationUrl)}" target="_blank" rel="noreferrer">Open authoritative source</a></p>
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
    <section class="section-block" id="release-scope">
      <div class="section-heading-row"><h2>Release scope</h2></div>
      <p>This public demonstration publishes a selected set of HGNC-mapped gene records derived from the supplied sources. It publishes derived evidence and provenance, not the original Excel workbooks.</p>
      <p class="caution-note">No standalone proteomic dataset was included in the supplied files. The atlas therefore does not label genes as having proteomic support in this release.</p>
    </section>`;

  setSectionNav([
    { id: "overview", label: "Source overview" },
    { id: "source-list", label: "Data collections" },
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
    [state.manifest, state.searchIndex, state.datasets] = await Promise.all([
      fetchJson(`${DATA_ROOT}/manifest.json`),
      fetchJson(`${DATA_ROOT}/search-index.json`),
      fetchJson(`${DATA_ROOT}/datasets.json`),
    ]);
    await renderRoute();
  } catch (error) {
    console.error(error);
    main.innerHTML = `<div class="error-state"><h1>Atlas data failed to load</h1><p>${escapeHtml(error.message)}</p><p>This site must be opened through a web server rather than directly from the filesystem.</p></div>`;
  }
}

window.addEventListener("hashchange", renderRoute);
initialize();

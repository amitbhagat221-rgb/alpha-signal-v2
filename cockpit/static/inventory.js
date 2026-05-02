// Data Inventory — vanilla JS click-to-sort + drag-to-reorder + persistence.
// Each table.inv-table is independent; layout state is keyed by data-domain-key
// in localStorage so the user's per-domain layout survives reloads.

(function () {
  const tables = document.querySelectorAll("table.inv-table");
  if (!tables.length) return;

  tables.forEach((table) => initTable(table));

  function initTable(table) {
    const key = table.dataset.domainKey || "default";
    const lsKey = `inv-layout-${key}`;
    const saved = loadState(lsKey);

    // Restore column order if any was saved.
    if (saved && Array.isArray(saved.columnOrder)) {
      reorderColumns(table, saved.columnOrder);
    }

    // Restore previous sort.
    if (saved && saved.sort) {
      sortTable(table, saved.sort.key, saved.sort.dir);
      markSortedHeader(table, saved.sort.key, saved.sort.dir);
    }

    wireSorting(table, lsKey);
    wireDragReorder(table, lsKey);
  }

  // ── Sort ────────────────────────────────────────────────────────────────
  function wireSorting(table, lsKey) {
    table.querySelectorAll("thead th").forEach((th) => {
      th.addEventListener("click", (e) => {
        // Don't sort if the click came from a drag-end.
        if (th._suppressClick) { th._suppressClick = false; return; }
        const k = th.dataset.key;
        if (!k) return;
        const current = table.dataset.sortKey === k ? table.dataset.sortDir : null;
        const dir = current === "asc" ? "desc" : "asc";
        sortTable(table, k, dir);
        markSortedHeader(table, k, dir);
        const state = loadState(lsKey) || {};
        state.sort = { key: k, dir };
        saveState(lsKey, state);
      });
    });
  }

  function markSortedHeader(table, key, dir) {
    table.querySelectorAll("thead th").forEach((th) => {
      th.classList.remove("sort-asc", "sort-desc");
      if (th.dataset.key === key) th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
    });
    table.dataset.sortKey = key;
    table.dataset.sortDir = dir;
  }

  function sortTable(table, key, dir) {
    const tbody = table.tBodies[0];
    const ths = Array.from(table.querySelectorAll("thead th"));
    const th = ths.find((t) => t.dataset.key === key);
    if (!th) return;
    const type = th.dataset.sort || "string";
    const rows = Array.from(tbody.rows);
    const sign = dir === "asc" ? 1 : -1;

    rows.sort((a, b) => {
      const av = cellSortValue(a, key, type);
      const bv = cellSortValue(b, key, type);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;        // empties always last
      if (bv == null) return -1;
      if (type === "number") return (av - bv) * sign;
      return String(av).localeCompare(String(bv)) * sign;
    });

    // Re-attach in new order. appendChild moves existing nodes.
    rows.forEach((r) => tbody.appendChild(r));
  }

  function cellSortValue(row, key, type) {
    const cell = row.querySelector(`td[data-key="${key}"]`);
    if (!cell) return null;
    const raw = (cell.textContent || "").trim();
    if (!raw || raw === "—") return null;
    if (type === "number") {
      // Strip commas, %, units like "121d" — pull the first number.
      const m = raw.replace(/,/g, "").match(/-?\d+(\.\d+)?/);
      return m ? parseFloat(m[0]) : null;
    }
    return raw.toLowerCase();
  }

  // ── Drag column reorder ─────────────────────────────────────────────────
  function wireDragReorder(table, lsKey) {
    const ths = Array.from(table.querySelectorAll("thead th"));
    let draggedKey = null;

    ths.forEach((th) => {
      th.draggable = true;

      th.addEventListener("dragstart", (e) => {
        draggedKey = th.dataset.key;
        th.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        // Some browsers need data set to enable drag.
        e.dataTransfer.setData("text/plain", draggedKey);
      });

      th.addEventListener("dragend", () => {
        th.classList.remove("dragging");
        // Suppress the synthetic click that fires after drag end on some browsers.
        th._suppressClick = true;
        ths.forEach((t) => t.classList.remove("drag-over"));
      });

      th.addEventListener("dragover", (e) => {
        if (!draggedKey || draggedKey === th.dataset.key) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        ths.forEach((t) => t.classList.remove("drag-over"));
        th.classList.add("drag-over");
      });

      th.addEventListener("dragleave", () => th.classList.remove("drag-over"));

      th.addEventListener("drop", (e) => {
        e.preventDefault();
        const targetKey = th.dataset.key;
        if (!draggedKey || draggedKey === targetKey) return;
        moveColumnBefore(table, draggedKey, targetKey);
        const order = Array.from(table.querySelectorAll("thead th")).map((t) => t.dataset.key);
        const state = loadState(lsKey) || {};
        state.columnOrder = order;
        saveState(lsKey, state);
        ths.forEach((t) => t.classList.remove("drag-over"));
      });
    });
  }

  function moveColumnBefore(table, srcKey, targetKey) {
    const ths = Array.from(table.querySelectorAll("thead th"));
    const srcIdx = ths.findIndex((t) => t.dataset.key === srcKey);
    const tgtIdx = ths.findIndex((t) => t.dataset.key === targetKey);
    if (srcIdx === -1 || tgtIdx === -1) return;
    moveCellAt(table.querySelector("thead tr"), srcIdx, tgtIdx);
    table.querySelectorAll("tbody tr").forEach((tr) => moveCellAt(tr, srcIdx, tgtIdx));
  }

  function moveCellAt(rowEl, srcIdx, tgtIdx) {
    const cells = Array.from(rowEl.children);
    const src = cells[srcIdx];
    const tgt = cells[tgtIdx];
    if (!src || !tgt) return;
    rowEl.insertBefore(src, tgt);
  }

  function reorderColumns(table, order) {
    // order = array of data-key strings. Reorder header + every body row.
    const ths = Array.from(table.querySelectorAll("thead th"));
    const currentKeys = ths.map((t) => t.dataset.key);
    if (order.length !== currentKeys.length) return; // schema drift — ignore saved order
    // Build position map: where each key currently sits.
    const reindex = order.map((k) => currentKeys.indexOf(k));
    if (reindex.some((i) => i === -1)) return;
    // Reorder a row by collecting cells in new order then re-appending.
    function reorderRow(rowEl) {
      const cells = Array.from(rowEl.children);
      const reordered = reindex.map((i) => cells[i]);
      reordered.forEach((c) => rowEl.appendChild(c));
    }
    reorderRow(table.querySelector("thead tr"));
    table.querySelectorAll("tbody tr").forEach(reorderRow);
  }

  // ── localStorage helpers ────────────────────────────────────────────────
  function loadState(key) {
    try { return JSON.parse(localStorage.getItem(key) || "null"); }
    catch (e) { return null; }
  }
  function saveState(key, state) {
    try { localStorage.setItem(key, JSON.stringify(state)); }
    catch (e) { /* quota; ignore */ }
  }
})();

"use strict";
let _chart = null;
let _firstLoad = true;
let _lastLoadTs = 0;
const _trades = new Map();
const REFRESH_INTERVAL = 30000;
const HISTORY_DEFAULT_LIMIT = 20;
let _historyExpanded = false;
const HALF_HOUR_SYNC_INTERVAL = 30 * 60 * 1000;

// ── helpers ──────────────────────────────────────────────────────────────────
function tempStr(lo, hi, unit) {
  if (unit === "M") {
    const fmt = (v) => (v === null ? null : v + "M");
    if (lo === null && hi !== null) return "<" + fmt(hi);
    if (hi === null && lo !== null) return "≥" + fmt(lo);
    return fmt(lo) + "–" + fmt(hi);
  }
  const d = "°" + unit;
  if (lo === null && hi !== null) return "<" + hi + d;
  if (hi === null && lo !== null) return "≥" + lo + d;
  return lo + "–" + hi + d;
}
function pClass(v) {
  return v >= 0 ? "g" : "r";
}
function eClass(e) {
  const a = Math.abs(e);
  return a >= 0.08 ? (e > 0 ? "g" : "r") : a >= 0.05 ? "y" : "md";
}
function tEdge(t) {
  return t.direction === "NO" ? -t.edge : t.edge;
} // edge do lado negociado (backend guarda o do lado YES)
function fmtAbs$(v) {
  return "$" + Math.abs(v).toFixed(2);
}
function fmtSign$(v) {
  return (v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(2);
}
function secsAgo(ts) {
  const s = Math.round(Date.now() / 1000 - ts);
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  return Math.floor(s / 3600) + "h ago";
}

function animCount(elId, to, fmtFn, duration = 1200) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!_firstLoad) {
    el.textContent = fmtFn(to);
    return;
  }
  const start = performance.now();
  (function tick(now) {
    const p = Math.min((now - start) / duration, 1);
    const ease = 1 - Math.pow(1 - p, 4); // Quartic ease out
    el.textContent = fmtFn(to * ease);
    if (p < 1) requestAnimationFrame(tick);
  })(performance.now());
}

function animateStagger(selector) {
  const els = document.querySelectorAll(selector);
  els.forEach((el, i) => {
    el.style.animationDelay = `${i * 0.05}s`;
    el.classList.add("slide-up");
    // Remove class and add back to re-trigger
    el.style.animation = "none";
    el.offsetHeight;
    el.style.animation = null;
  });
}

// ── hero ─────────────────────────────────────────────────────────────────────
function renderHero(d) {
  const p = d.pnl;
  if (_firstLoad) {
    const clobLine =
      _mode === "live"
        ? '<div class="hero-sub" id="hv-br-clob" style="color:var(--muted);margin-top:2px">fetching CLOB balance…</div>'
        : "";
    document.getElementById("hero-grid").innerHTML = `
      <div class="hero-card slide-up" style="animation-delay: 0.05s">
        <div class="hero-label">Bankroll${_mode === "live" ? ' <span style="font-size:9px;color:var(--green);letter-spacing:1px">● LIVE</span>' : ""}</div>
        <div class="hero-value a" id="hv-br">—</div>
        <div class="hero-sub" id="hv-br-sub"></div>
        ${clobLine}
      </div>
      <div class="hero-card slide-up" style="animation-delay: 0.1s">
        <div class="hero-label">Total PnL</div>
        <div class="hero-value" id="hv-pnl">—</div>
        <div class="hero-sub" id="hv-pnl-sub"></div>
      </div>
      <div class="hero-card slide-up" style="animation-delay: 0.15s">
        <div class="hero-label">Win Rate</div>
        <div class="hero-value" id="hv-wr">—</div>
        <div class="hero-sub" id="hv-wr-sub"></div>
      </div>
    `;
  }
  const ev =
    p.n_resolved > 0
      ? (p.win_rate / 100) * Math.abs(p.avg_win) -
        (1 - p.win_rate / 100) * Math.abs(p.avg_loss)
      : null;
  document.getElementById("hv-pnl").className =
    "hero-value " + pClass(p.total_pnl);
  document.getElementById("hv-wr").className =
    "hero-value " + (ev === null ? "md" : ev > 0 ? "g" : ev > -5 ? "y" : "r");
  if (d.live_pm_ui && p.portfolio_value !== undefined) {
    document.getElementById("hv-br-sub").textContent =
      "portfolio $" +
      p.portfolio_value.toFixed(2) +
      " · cash $" +
      (p.cash != null ? p.cash : p.bankroll).toFixed(2) +
      " · in positions $" +
      (p.positions_value != null ? p.positions_value : p.deployed).toFixed(2);
    document.getElementById("hv-pnl-sub").textContent =
      "unrl " +
      (p.unrealized_pnl >= 0 ? "+$" : "-$") +
      Math.abs(p.unrealized_pnl).toFixed(2) +
      " · real " +
      (p.realized_pnl >= 0 ? "+$" : "-$") +
      Math.abs(p.realized_pnl).toFixed(2) +
      " · ROI " +
      (p.pct_return >= 0 ? "+" : "") +
      p.pct_return.toFixed(1) +
      "% (est.)";
  } else {
    document.getElementById("hv-br-sub").textContent =
      p.n_open + " open · $" + p.deployed.toFixed(0) + " deployed";
    const startBr = p.bankroll + p.deployed - p.total_pnl;
    document.getElementById("hv-pnl-sub").textContent =
      (p.pct_return >= 0 ? "+" : "") +
      p.pct_return.toFixed(1) +
      "% · $" +
      startBr.toFixed(0) +
      " starting";
  }
  document.getElementById("hv-wr-sub").textContent =
    p.n_wins + "W / " + p.n_losses + "L · " + p.n_resolved + " closed";
  animCount("hv-br", p.bankroll, (v) => "$" + v.toFixed(2));
  animCount(
    "hv-pnl",
    p.total_pnl,
    (v) => (v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(2),
  );
  animCount("hv-wr", p.win_rate, (v) => v.toFixed(1) + "%");
  const modeText = (d.mode || _mode).toUpperCase();
  const src = document.getElementById("data-mode-text");
  if (src) {
    src.textContent = `Data source: ${modeText} (${d.db_file || "db"}) · open=${d.open_count ?? (d.positions || []).length} · resolved=${d.history_count ?? (d.history || []).length}`;
  }
}

// ── pills ─────────────────────────────────────────────────────────────────────
function renderPills(d) {
  const p = d.pnl,
    c = d.cal,
    s = d.sharpe;
  let rows;
  if (d.live_pm_ui) {
    rows = [
      {
        label: "Cash",
        val: "$" + (p.cash != null ? p.cash : p.bankroll).toFixed(2),
        cls: "md",
      },
      {
        label: "Positions $",
        val:
          "$" +
          (p.positions_value != null ? p.positions_value : p.deployed).toFixed(
            2,
          ),
        cls: "md",
      },
      {
        label: "Unrealized",
        val:
          (p.unrealized_pnl >= 0 ? "+$" : "-$") +
          Math.abs(p.unrealized_pnl).toFixed(2),
        cls: pClass(p.unrealized_pnl),
      },
      {
        label: "Realized",
        val:
          (p.realized_pnl >= 0 ? "+$" : "-$") +
          Math.abs(p.realized_pnl).toFixed(2),
        cls: pClass(p.realized_pnl),
      },
      { label: "Avg Win", val: fmtAbs$(p.avg_win), cls: "g" },
      { label: "Avg Loss", val: fmtAbs$(p.avg_loss), cls: "r" },
    ];
  } else {
    rows = [
      { label: "Avg Win", val: fmtAbs$(p.avg_win), cls: "g" },
      { label: "Avg Loss", val: fmtAbs$(p.avg_loss), cls: "r" },
      {
        label: "Sharpe",
        val: s !== null ? s.toFixed(2) : "—",
        cls: s !== null && s > 0 ? "g" : "md",
      },
      {
        label: "Dir Acc",
        val: c.accuracy.toFixed(1) + "%",
        cls: c.accuracy >= 50 ? "g" : c.accuracy >= 40 ? "y" : "r",
      },
      {
        label: "Model Err",
        val: c.mean_model_error.toFixed(3),
        cls: c.mean_model_error < 0.22 ? "g" : "md",
      },
      {
        label: "Market Err",
        val: c.mean_market_error.toFixed(3),
        cls: c.mean_market_error < 0.22 ? "g" : "md",
      },
    ];
  }
  document.getElementById("pills").innerHTML = rows
    .map(
      (r, i) => `
    <div class="pill slide-up" style="animation-delay: ${0.2 + i * 0.05}s">
      <div class="pill-label">${r.label}</div>
      <div class="pill-value mono ${r.cls}">${r.val}</div>
    </div>
  `,
    )
    .join("");
}

// ── positions ─────────────────────────────────────────────────────────────────
function renderPositions(pos) {
  const card = document.getElementById("pos-card");
  if (!pos.length) {
    card.innerHTML =
      '<div class="card-hdr"><span class="card-title glow-text">Open Positions</span></div><div class="empty">No open positions.</div>';
    return;
  }
  pos.forEach((t) => _trades.set(String(t.trade_id), t));
  const pm = pos[0] && pos[0].pm_row;
  const rows = pos
    .map((p, i) => {
      if (pm) {
        const side =
          '<span class="badge b-yes">' +
          String(p.direction || "—").replace(/</g, "") +
          "</span>";
        const ep =
          p.entry_price != null ? (p.entry_price * 100).toFixed(1) + "¢" : "—";
        const mkt =
          p.model_prob != null ? (p.model_prob * 100).toFixed(1) + "%" : "—";
        const pnl = p.edge;
        return `<tr class="${p.clob_token_yes ? "row-click" : ""} slide-up" style="animation-delay: ${i * 0.03}s" data-id="${p.trade_id}">
        <td class="fw6" style="max-width:220px;white-space:normal;line-height:1.25">${(p.city || "").slice(0, 120)}</td>
        <td class="mono md">${p.target_date || "—"}</td>
        <td>${side}</td>
        <td class="tr mono">${ep}</td>
        <td class="tr mono fw6">${p.size_usdc > 0 ? "$" + p.size_usdc.toFixed(2) : '<span class="md">—</span>'}</td>
        <td class="tr mono md">${mkt}</td>
        <td class="tr mono ${eClass(pnl)}">${pnl >= 0 ? "+$" : "-$"}${Math.abs(pnl).toFixed(2)}</td>
      </tr>`;
      }
      const dir =
        p.direction === "YES"
          ? '<span class="badge b-yes">YES</span>'
          : '<span class="badge b-no">NO</span>';
      const te = tEdge(p);
      return `<tr class="${p.clob_token_yes ? "row-click" : ""} slide-up" style="animation-delay: ${i * 0.03}s" data-id="${p.trade_id}">
      <td class="fw6">${p.city}</td>
      <td class="mono md">${p.target_date}</td>
      <td>${dir} <span class="mono md" style="font-size:11px">${tempStr(p.bucket_lo, p.bucket_hi, p.bucket_unit)}</span></td>
      <td class="tr mono">${(p.entry_price * 100).toFixed(1)}¢</td>
      <td class="tr mono fw6">${p.size_usdc > 0 ? "$" + p.size_usdc.toFixed(2) : '<span class="md">—</span>'}</td>
      <td class="tr mono md">${(p.model_prob * 100).toFixed(1)}%</td>
      <td class="tr mono ${eClass(te)}">${te >= 0 ? "+" : ""}${te.toFixed(3)}</td>
    </tr>`;
    })
    .join("");
  const thead = pm
    ? '<thead><tr><th>Market</th><th>End</th><th>Side</th><th class="tr">Avg</th><th class="tr">Value</th><th class="tr">Mkt</th><th class="tr">PnL</th></tr></thead>'
    : '<thead><tr><th>City</th><th>Date</th><th>Bet</th><th class="tr">Entry</th><th class="tr">Size</th><th class="tr">Model %</th><th class="tr">Edge</th></tr></thead>';
  card.innerHTML = `
    <div class="card-hdr">
      <span class="card-title glow-text">Open Positions <span class="card-badge">${pos.length}</span></span>
      <span class="card-hint">${pm ? "Polymarket API" : "click row for chart"}</span>
    </div>
    <div class="tbl-wrap"><table>
      ${thead}
      <tbody>${rows}</tbody>
    </table></div>`;
  card.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      const t = _trades.get(row.dataset.id);
      if (t) openModal(t);
    });
  });
}

// ── exposure ──────────────────────────────────────────────────────────────────
function renderExposure(pos) {
  const card = document.getElementById("exp-card");
  const by = {};
  let total = 0;
  pos.forEach((p) => {
    if (!by[p.city]) by[p.city] = { amt: 0, yes: 0, no: 0 };
    by[p.city].amt += p.size_usdc;
    by[p.city][p.direction === "YES" ? "yes" : "no"]++;
    total += p.size_usdc;
  });
  const sorted = Object.entries(by).sort((a, b) => b[1].amt - a[1].amt);
  if (!sorted.length) {
    card.innerHTML =
      '<div class="card-hdr"><span class="card-title glow-text">Exposure</span></div><div class="empty">—</div>';
    return;
  }
  const rows = sorted
    .map(([city, s], i) => {
      const pct = total > 0 ? (s.amt / total) * 100 : 0;
      const t2 = s.yes + s.no;
      const yp = t2 > 0 ? (s.yes / t2) * 100 : 50;
      const ynLabel = `<span class="a">${s.yes}Y</span><span class="md"> · </span><span class="p">${s.no}N</span>`;
      return `<div class="exp-row slide-up" style="animation-delay: ${i * 0.05}s">
      <span class="exp-city" title="${city}">${city}</span>
      <span class="exp-amt mono" style="font-size:11px">${ynLabel}</span>
      <div class="exp-bar">
        <div class="exp-bar-y" style="width:${yp.toFixed(0)}%;"></div>
        <div class="exp-bar-n" style="width:${(100 - yp).toFixed(0)}%;"></div>
      </div>
      <span class="exp-pct">${pct.toFixed(0)}%</span>
    </div>`;
    })
    .join("");
  card.innerHTML = `<div class="card-hdr"><span class="card-title glow-text">Exposure</span><span class="card-badge">$${total.toFixed(0)}</span></div>${rows}`;
}

// ── history ───────────────────────────────────────────────────────────────────
function renderHistory(hist) {
  const card = document.getElementById("hist-card");
  if (!hist.length) {
    card.innerHTML =
      '<div class="card-hdr"><span class="card-title glow-text">Trade History</span></div><div class="empty">No resolved trades yet.</div>';
    return;
  }
  const shown = _historyExpanded ? hist : hist.slice(0, HISTORY_DEFAULT_LIMIT);
  const pm = shown[0] && shown[0].pm_row;
  hist.forEach((t) => _trades.set(String(t.trade_id), t));
  const rows = shown
    .map((t, i) => {
      const pnl = t.pnl || 0;
      if (pm) {
        const res =
          t.status === "won"
            ? '<span class="badge b-won">WIN</span>'
            : '<span class="badge b-lost">LOSS</span>';
        const side =
          '<span class="badge b-yes">' +
          String(t.direction || "—").replace(/</g, "") +
          "</span>";
        return `<tr class="${t.clob_token_yes ? "row-click" : ""} slide-up" style="animation-delay: ${i * 0.03}s" data-id="${t.trade_id}">
        <td class="fw6" style="max-width:220px;white-space:normal;line-height:1.25">${(t.city || "").slice(0, 120)}</td>
        <td class="mono md">${t.target_date || "—"}</td>
        <td>${side}</td>
        <td>${res}</td>
        <td class="tr mono ${pClass(pnl)} fw6">${fmtSign$(pnl)}</td>
      </tr>`;
      }
      const res =
        t.status === "won"
          ? '<span class="badge b-won">WON</span>'
          : t.status === "lost"
            ? '<span class="badge b-lost">LOST</span>'
            : t.status === "stop_loss"
              ? '<span class="badge b-stop">STOP</span>'
              : '<span class="badge b-void">VOID</span>';
      const dir =
        t.direction === "YES"
          ? '<span class="badge b-yes">YES</span>'
          : '<span class="badge b-no">NO</span>';
      const actual =
        t.actual_high_c !== null && t.actual_high_c !== undefined
          ? t.actual_high_c.toFixed(1) + "°C"
          : "—";
      return `<tr class="${t.clob_token_yes ? "row-click" : ""} slide-up" style="animation-delay: ${i * 0.03}s" data-id="${t.trade_id}">
      <td class="fw6">${t.city}</td>
      <td class="mono md">${t.target_date}</td>
      <td>${dir} <span class="mono md" style="font-size:11px">${tempStr(t.bucket_lo, t.bucket_hi, t.bucket_unit)}</span></td>
      <td>${res}</td>
      <td class="tr mono ${pClass(pnl)} fw6">${fmtSign$(pnl)}</td>
      <td class="tr mono md">${actual}</td>
    </tr>`;
    })
    .join("");
  const histTitle = pm ? "Closed (Polymarket)" : "Trade History";
  const histThead = pm
    ? '<thead><tr><th>Market</th><th>End</th><th>Side</th><th>Result</th><th class="tr">PnL</th></tr></thead>'
    : '<thead><tr><th>City</th><th>Date</th><th>Bet</th><th>Result</th><th class="tr">PnL</th><th class="tr">Actual</th></tr></thead>';
  card.innerHTML = `
    <div class="card-hdr">
      <span class="card-title glow-text">${histTitle} <span class="card-badge">${hist.length}</span></span>
      <span class="card-tools">
        ${hist.length > HISTORY_DEFAULT_LIMIT ? `<button class="link-btn" id="hist-toggle">${_historyExpanded ? "Show less" : `Show all (${hist.length})`}</button>` : ""}
      </span>
    </div>
    <div class="tbl-wrap"><table>
    ${histThead}
    <tbody>${rows}</tbody></table></div>`;
  const histToggle = document.getElementById("hist-toggle");
  if (histToggle) {
    histToggle.addEventListener("click", () => {
      _historyExpanded = !_historyExpanded;
      renderHistory(hist);
    });
  }
  card.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      const t = _trades.get(row.dataset.id);
      if (t) openModal(t);
    });
  });
}

// ── stations ──────────────────────────────────────────────────────────────────
function renderStations(st) {
  const ready = st.filter((s) => s.status === "ready").length;
  const warming = st.length - ready;
  const rows = st
    .map((s, i) => {
      const badge =
        s.status === "ready"
          ? '<span class="badge b-ready">Ready</span>'
          : '<span class="badge b-warmup">Warming</span>';
      const bias =
        s.avg_bias !== null && s.avg_bias !== undefined
          ? s.avg_bias.toFixed(2) + "°"
          : "—";
      return `<tr class="slide-up" style="animation-delay: ${i * 0.02}s">
      <td class="fw6">${s.city}</td><td class="mono md">${s.icao}</td>
      <td>${badge}</td><td class="tr mono">${s.history_days}</td>
      <td class="tr mono md">${bias}</td>
    </tr>`;
    })
    .join("");
  document.getElementById("stn-card").innerHTML = `
    <div class="card-hdr"><span class="card-title glow-text">Stations</span>
    <span class="card-badge">${ready}/${st.length} ready</span></div>
    <div class="tbl-wrap"><table>
    <thead><tr><th>City</th><th>ICAO</th><th>Status</th><th class="tr">Days</th><th class="tr">Avg Bias</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function _fmtIso(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toISOString().slice(11, 19) + "Z";
  } catch {
    return "—";
  }
}

function renderOps(ops) {
  const card = document.getElementById("ops-card");
  if (!card || !ops || !ops.jobs) return;
  const s = ops.jobs["scan"] || {};
  const e = ops.jobs["exit-scan"] || {};
  const r = ops.jobs["resolve"] || {};
  const om = (ops.datasources && ops.datasources.openmeteo) || {};
  const line = (k, v, cls = "md") =>
    `<div class="ops-line"><span class="ops-k">${k}</span><span class="ops-v ${cls}">${v}</span></div>`;
  card.innerHTML = `
    <div class="card-hdr"><span class="card-title glow-text">Ops</span></div>
    <div class="ops-wrap">
      ${line("Open-Meteo health", String(om.state || "ok").toUpperCase(), om.state === "offline" ? "r" : om.state === "degraded" ? "y" : "g")}
      ${line("Scan last success", _fmtIso(s.last_success_at))}
      ${line("Exit-scan last success", _fmtIso(e.last_success_at))}
      ${line("Resolve last success", _fmtIso(r.last_success_at))}
      ${line("Scan p95 duration", s.p95_duration_s ? s.p95_duration_s.toFixed(1) + "s" : "—")}
      ${line("Last error", s.last_error || e.last_error || r.last_error || "none", s.last_error || e.last_error || r.last_error ? "r" : "g")}
      ${line("Locks", `scan:${s.lock && s.lock.locked ? "ON" : "off"} exit:${e.lock && e.lock.locked ? "ON" : "off"} resolve:${r.lock && r.lock.locked ? "ON" : "off"}`)}
    </div>`;
}

// ── modal ─────────────────────────────────────────────────────────────────────
function openModal(trade) {
  const dir = trade.direction;
  document.getElementById("m-title").textContent =
    trade.question || trade.city + " " + trade.target_date;
  document.getElementById("m-dir").innerHTML =
    dir === "YES"
      ? '<span class="badge b-yes">YES</span>'
      : '<span class="badge b-no">NO</span>';
  document.getElementById("m-entry").textContent =
    "$" + trade.entry_price.toFixed(4);
  document.getElementById("m-size").textContent =
    "$" + trade.size_usdc.toFixed(2);
  document.getElementById("m-model").textContent = trade.model_prob.toFixed(3);
  document.getElementById("m-current").textContent = "…";
  document.getElementById("m-current").className = "m-stat-val mono md";
  const eEl = document.getElementById("m-edge");
  const te = tEdge(trade);
  eEl.className = "m-stat-val mono " + eClass(te);
  eEl.textContent = (te >= 0 ? "+" : "") + te.toFixed(3);
  document.getElementById("m-pm-link").href = "#";
  const cl = document.getElementById("chart-load");
  cl.style.display = "flex";
  cl.innerHTML = '<div class="spin-neon"></div><span>Decrypting feed...</span>';
  document.getElementById("price-chart").style.display = "none";
  if (_chart) {
    _chart.destroy();
    _chart = null;
  }
  document.getElementById("overlay").classList.add("open");

  if (trade.clob_token_yes) {
    Promise.all([
      fetch(
        "/api/price-history?token=" + encodeURIComponent(trade.clob_token_yes),
      ).then((r) => r.json()),
      fetch(
        "/api/market-meta?token=" + encodeURIComponent(trade.clob_token_yes),
      ).then((r) => r.json()),
    ])
      .then(([hist, meta]) => {
        if (meta.event_slug)
          document.getElementById("m-pm-link").href =
            "https://polymarket.com/event/" + meta.event_slug + "/" + meta.slug;
        const pts = hist.history || [];
        if (!pts.length) {
          cl.innerHTML = "No price history available.";
          return;
        }
        const last = pts[pts.length - 1].p;
        const entryYES =
          dir === "YES" ? trade.entry_price : 1 - trade.entry_price;
        const curEl = document.getElementById("m-current");
        curEl.textContent = "$" + last.toFixed(4);
        curEl.className = "m-stat-val mono " + (last >= entryYES ? "g" : "r");
        renderChart(pts, entryYES);
      })
      .catch(() => {
        cl.innerHTML = "Could not load price data.";
      });
  } else {
    cl.innerHTML = "No CLOB token available.";
  }
}

function renderChart(pts, entryYES) {
  const labels = pts.map((p) => {
    const d = new Date(p.t * 1000);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  });
  const prices = pts.map((p) => p.p);
  const last = prices[prices.length - 1];
  const up = last >= entryYES;
  const lc = "#FF4D00";
  const fillColor = "rgba(255, 77, 0, 0.1)";
  document.getElementById("chart-load").style.display = "none";
  const canvas = document.getElementById("price-chart");
  canvas.style.display = "block";
  const ctx = canvas.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 300);
  grad.addColorStop(0, fillColor);
  grad.addColorStop(1, "rgba(0,0,0,0)");
  _chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "YES Price",
          data: prices,
          borderColor: lc,
          backgroundColor: grad,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: lc,
          pointHoverBorderColor: "#fff",
          fill: true,
          tension: 0.2,
        },
        {
          label: "Entry",
          data: Array(prices.length).fill(entryYES),
          borderColor: "rgba(255,255,255,0.4)",
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 800, easing: "easeOutQuart" },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: {
            color: "#888",
            font: { size: 12, family: "Inter" },
            boxWidth: 12,
            padding: 16,
          },
        },
        tooltip: {
          backgroundColor: "#111",
          borderColor: "rgba(255,255,255,0.1)",
          borderWidth: 1,
          titleColor: "#888",
          bodyColor: "#fff",
          padding: 12,
          cornerRadius: 12,
          titleFont: { size: 12, family: "Inter" },
          bodyFont: { size: 14, family: "Inter", weight: "600" },
          callbacks: {
            label: (ctx) =>
              " " + ctx.dataset.label + ": $" + ctx.parsed.y.toFixed(4),
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: "#555",
            maxTicksLimit: 5,
            font: { size: 12, family: "Inter" },
          },
          grid: { color: "rgba(255,255,255,0.03)" },
          border: { color: "transparent" },
        },
        y: {
          ticks: {
            color: "#555",
            font: { size: 12, family: "Inter", variantNumeric: "tabular-nums" },
            callback: (v) => "$" + v.toFixed(2),
          },
          grid: { color: "rgba(255,255,255,0.03)" },
          border: { color: "transparent" },
          min: 0,
          max: 1,
        },
      },
    },
  });
}

function closeModal() {
  document.getElementById("overlay").classList.remove("open");
  if (_chart) {
    _chart.destroy();
    _chart = null;
  }
}
function maybeClose(e) {
  if (e.target === document.getElementById("overlay")) closeModal();
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

// ── mode toggle ───────────────────────────────────────────────────────────────
var _mode = localStorage.getItem("dashboard_mode") || "paper";
function setMode(m) {
  _mode = m;
  _historyExpanded = false;
  localStorage.setItem("dashboard_mode", m);
  const url = new URL(window.location.href);
  url.searchParams.set("mode", m);
  history.replaceState({}, "", url.toString());
  _firstLoad = true;
  document
    .getElementById("mode-paper")
    .classList.toggle("active", m === "paper");
  document.getElementById("mode-live").classList.toggle("active", m === "live");
  document.body.classList.toggle("live-mode", m === "live");
  if (m === "live") refreshClobBalance();
  load(false);
}

// ── CLOB balance ──────────────────────────────────────────────────────────────
function refreshClobBalance() {
  fetch("/api/clob-balance")
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((d) => {
      const el = document.getElementById("hv-br-clob");
      if (!el) return;
      if (d.balance !== null && d.balance !== undefined) {
        el.textContent = "CLOB wallet: $" + d.balance.toFixed(2);
        el.style.color = "var(--green)";
      } else {
        el.textContent = "CLOB wallet: unavailable";
        el.style.color = "";
      }
    })
    .catch(() => {
      const el = document.getElementById("hv-br-clob");
      if (el) {
        el.textContent = "CLOB wallet: unavailable";
        el.style.color = "";
      }
    });
}

// ── main load ─────────────────────────────────────────────────────────────────
var _loading = false;
function load(force) {
  if (_loading) return;
  _loading = true;
  const icon = document.getElementById("refresh-icon");
  icon.classList.add("spin");
  const url = "/api/data?mode=" + _mode + (force ? "&force=1" : "");
  fetch(url)
    .then((r) => r.json())
    .then((d) => {
      _loading = false;
      icon.classList.remove("spin");
      if (d.error && !d.positions) {
        console.error("Dashboard error:", d.error);
        return;
      }
      const firstRender = _firstLoad;
      document.getElementById("stale-bar").classList.toggle("show", !!d.stale);
      document.getElementById("ts").textContent = d.ts || "—";
      _lastLoadTs = Date.now() / 1000;
      renderHero(d);
      renderPills(d);
      renderPositions(d.positions || []);
      renderExposure(d.positions || []);
      renderHistory(d.history || []);
      renderStations(d.stations || []);
      renderOps(d.ops || {});
      if (_mode === "live" && firstRender) refreshClobBalance();
      _firstLoad = false;
    })
    .catch((err) => {
      _loading = false;
      icon.classList.remove("spin");
      console.error("Load failed:", err);
    });
}

// ── age counter ───────────────────────────────────────────────────────────────
setInterval(() => {
  if (_lastLoadTs > 0) {
    document.getElementById("ts-age").textContent =
      "updated " + secsAgo(_lastLoadTs);
  }
}, 5000);

// ── auto-refresh ──────────────────────────────────────────────────────────────
var _timer = setInterval(() => load(false), REFRESH_INTERVAL);
var _halfHourTimer = setInterval(() => {
  load(true); // hard refresh to align with 30m risk-management cadence
  if (_mode === "live") refreshClobBalance();
}, HALF_HOUR_SYNC_INTERVAL);
document.addEventListener("visibilitychange", () => {
  clearInterval(_timer);
  clearInterval(_halfHourTimer);
  if (!document.hidden) {
    load(false);
    _timer = setInterval(() => load(false), REFRESH_INTERVAL);
    _halfHourTimer = setInterval(() => {
      load(true);
      if (_mode === "live") refreshClobBalance();
    }, HALF_HOUR_SYNC_INTERVAL);
  }
});

// ── action buttons ────────────────────────────────────────────────────────────
var _ICONS = { scan: "⚡", resolve: "✓" };
var _polls = {};

function showToast(text, err) {
  var t = document.getElementById("job-toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "job-toast";
    t.className = "toast";
    t.innerHTML =
      '<button class="toast-close" onclick="hideToast()">✕</button><span id="toast-body"></span>';
    document.body.appendChild(t);
  }
  document.getElementById("toast-body").textContent = text;
  t.style.borderColor = err ? "rgba(255,42,95,0.4)" : "rgba(0,255,163,0.35)";
  t.classList.add("show");
}
function hideToast() {
  var t = document.getElementById("job-toast");
  if (t) t.classList.remove("show");
}

function runCmd(cmd) {
  var btn = document.getElementById("btn-" + cmd),
    icon = document.getElementById(cmd + "-icon");
  btn.disabled = true;
  btn.classList.add("running");
  icon.innerHTML = "";
  icon.classList.add("spin-neon");
  hideToast();
  fetch("/api/run/" + cmd + "?mode=" + _mode, { method: "POST" })
    .then((r) => r.json())
    .then((d) => {
      if (d.error) {
        finishBtn(cmd, false, d.error);
        return;
      }
      pollJob(cmd, d.job_id);
    })
    .catch((e) => finishBtn(cmd, false, String(e)));
}

function pollJob(cmd, jobId) {
  clearTimeout(_polls[cmd]);
  _polls[cmd] = setTimeout(() => {
    fetch("/api/run/status/" + jobId)
      .then((r) => r.json())
      .then((d) => {
        if (d.status === "running") {
          pollJob(cmd, jobId);
          return;
        }
        finishBtn(cmd, d.status === "done", d.output || "");
        if (d.status === "done") setTimeout(() => load(true), 800);
      })
      .catch((e) => finishBtn(cmd, false, String(e)));
  }, 1500);
}

function finishBtn(cmd, ok, output) {
  var btn = document.getElementById("btn-" + cmd),
    icon = document.getElementById(cmd + "-icon");
  btn.disabled = false;
  btn.classList.remove("running");
  btn.classList.add(ok ? "ok" : "err");
  icon.classList.remove("spin-neon");
  icon.textContent = ok ? "✓" : "✗";
  showToast(output || (ok ? "Done." : "Failed."), !ok);
  setTimeout(() => {
    btn.classList.remove("ok", "err");
    icon.textContent = _ICONS[cmd];
  }, 5000);
}

// init — restore mode from URL/local storage (default paper)
(() => {
  const q = new URLSearchParams(window.location.search).get("mode");
  if (q === "paper" || q === "live") {
    _mode = q;
  }
  setMode(_mode);
})();

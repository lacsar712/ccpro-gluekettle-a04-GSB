import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  view: "board",
  user: null,
  board: null,
  picked: null,
  peak: "96",
  rack: null,
  rackFilter: "all",
  occupyKettleId: "",
  slotNo: "",
  err: "",
  username: "admin",
  password: "123456",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function refreshBoard() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.picked;
  }
}

async function refreshRack() {
  const q = state.rackFilter === "all" ? "" : `?kettle_id=${encodeURIComponent(state.rackFilter)}`;
  state.rack = await api(`/api/rack${q}`);
}

async function refresh() {
  state.err = "";
  if (!state.user) state.user = await api("/api/auth/me");
  await refreshBoard();
  if (state.view === "rack") await refreshRack();
  render();
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  location.reload();
}

function renderLogin() {
  const box = el(`<div class="wrap">
    <h1>骨巷熬胶坊</h1>
    <p>一排熬锅作业台，原生页面，无前端框架。</p>
    <form autocomplete="off">
      <label>用户名
        <input name="u" autocomplete="off" value="${esc(state.username)}" />
      </label>
      <label>密码
        <input name="p" type="password" autocomplete="off" value="${esc(state.password)}" />
      </label>
      <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
      <button>登录</button>
    </form>
    <p class="err">${esc(state.err)}</p>
  </div>`);
  box.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    state.err = "";
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: box.querySelector("[name=u]").value,
          password: box.querySelector("[name=p]").value,
        }),
      });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      state.ready = true;
      state.user = data.user;
      await refreshBoard();
      if (state.view === "rack") await refreshRack();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function renderTopbar() {
  const roleLabel = state.user.role === "admin" ? "管理员" : "操作工";
  const bar = el(`<header class="topbar">
    <nav>
      <button data-view="board" class="${state.view === "board" ? "active" : ""}">锅位作业台</button>
      <button data-view="rack" class="${state.view === "rack" ? "active" : ""}">冷却架</button>
    </nav>
    <div class="who">${esc(state.user.username)} · ${roleLabel} <button id="logout">登出</button></div>
  </header>`);
  bar.querySelectorAll("[data-view]").forEach((b) => {
    b.onclick = async () => {
      state.view = b.dataset.view;
      state.err = "";
      if (state.view === "rack") await refreshRack().catch((e) => (state.err = e.message));
      render();
    };
  });
  bar.querySelector("#logout").onclick = logout;
  return bar;
}

function renderBoard(box) {
  const row = box.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}"><strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });

  if (!state.picked) return;
  const k = state.picked;
  const d = box.querySelector(".drawer");
  d.innerHTML = `<h3>${esc(k.code)} · ${LABELS[k.status]}</h3>
    <p>最近峰值：${k.latestPeakC ?? "无"} ℃ · ${k.cookCount} 次</p>
    <input id="peak" value="${esc(state.peak)}" />
    <button id="log">登记峰值</button>
    <div class="statusbtns">
      <button data-s="cold">冷锅</button>
      <button data-s="boiling">熬煮中</button>
      <button data-s="drawn">已出胶</button>
    </div>
    ${
      k.status === "drawn" && k.rackSlotNo == null
        ? `<p class="hint">该锅已出胶，须先到「冷却架」占用一个架位，才能拨回冷锅。</p>`
        : ""
    }`;
  d.querySelector("#log").onclick = async () => {
    state.peak = d.querySelector("#peak").value;
    try {
      state.picked = await api(`/api/kettles/${k.id}/cooks`, {
        method: "POST",
        body: JSON.stringify({ peakTempC: Number(state.peak) }),
      });
      await refreshBoard();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  d.querySelectorAll("[data-s]").forEach((b) => {
    b.onclick = async () => {
      try {
        state.picked = await api(`/api/kettles/${k.id}/status`, {
          method: "POST",
          body: JSON.stringify({ status: b.dataset.s }),
        });
        await refreshBoard();
        render();
      } catch (ex) {
        // 已出胶且未占架位时，后端以中文挡住拨回冷锅。
        state.err = ex.message;
        render();
      }
    };
  });
}

function renderRack(box) {
  const rack = state.rack;
  const kettles = state.board.kettles;
  const page = box.querySelector(".rackpage");

  const filterOpts =
    `<option value="all">全部锅</option>` +
    kettles
      .map(
        (k) =>
          `<option value="${k.id}" ${String(k.id) === String(state.rackFilter) ? "selected" : ""}>${esc(k.code)} · ${LABELS[k.status]}</option>`
      )
      .join("");
  const drawnKettles = kettles.filter((k) => k.status === "drawn");
  if (!state.occupyKettleId && drawnKettles[0]) state.occupyKettleId = String(drawnKettles[0].id);
  const occupyOpts =
    drawnKettles.length === 0
      ? `<option value="">（暂无可占位的已出胶锅）</option>`
      : drawnKettles
          .map(
            (k) =>
              `<option value="${k.id}" ${String(k.id) === String(state.occupyKettleId) ? "selected" : ""}>${esc(k.code)}</option>`
          )
          .join("");
  const isAdmin = state.user.role === "admin";

  page.innerHTML = `
    <h2>冷却架</h2>
    <p class="hint">架位号 ${rack.slotMin}–${rack.slotMax}。操作工可占位；释放仅管理员。同一架位号被别锅占用（撞车）时禁止入库。</p>
    <div class="rack-grid"></div>
    <form class="occupy-form" autocomplete="off">
      <label>锅
        <select id="occ-kettle">${occupyOpts}</select>
      </label>
      <label>架位号
        <input id="occ-slot" type="number" min="${rack.slotMin}" max="${rack.slotMax}" placeholder="1–${rack.slotMax}" value="${esc(state.slotNo)}" />
      </label>
      <button id="occ-btn" ${drawnKettles.length === 0 ? "disabled" : ""}>占位</button>
    </form>
    <div class="rack-filter">
      <label>按锅筛选
        <select id="rack-filter">${filterOpts}</select>
      </label>
    </div>
    <table class="rack-table">
      <thead><tr><th>架位号</th><th>锅</th><th>占用人</th><th>占用时刻</th><th></th></tr></thead>
      <tbody></tbody>
    </table>`;

  // 架位格子：未释放占用按号标记。
  const grid = page.querySelector(".rack-grid");
  const taken = new Map(rack.occupations.map((o) => [o.slotNo, o]));
  for (let n = rack.slotMin; n <= rack.slotMax; n++) {
    const o = taken.get(n);
    const cell = el(
      `<div class="slot ${o ? "taken" : "free"}" title="${o ? `${esc(o.kettleCode)} · ${esc(o.occupiedBy)}` : "空"}">
        <span class="slot-no">${n}</span>${o ? `<span class="slot-k">${esc(o.kettleCode)}</span>` : ""}
      </div>`
    );
    grid.append(cell);
  }

  const tbody = page.querySelector(".rack-table tbody");
  if (rack.occupations.length === 0) {
    tbody.append(el(`<tr><td colspan="5" class="hint">当前筛选下没有未释放占用。</td></tr>`));
  }
  rack.occupations.forEach((o) => {
    const tr = el(`<tr>
      <td>${o.slotNo}</td>
      <td>${esc(o.kettleCode)}</td>
      <td>${esc(o.occupiedBy)}</td>
      <td>${esc((o.occupiedAt || "").replace("T", " ").slice(0, 19))}</td>
      <td>${isAdmin ? `<button data-release="${o.id}">释放</button>` : `<span class="hint">仅管理员</span>`}</td>
    </tr>`);
    const rb = tr.querySelector("[data-release]");
    if (rb) {
      rb.onclick = async () => {
        try {
          await api(`/api/rack/occupations/${o.id}/release`, { method: "POST" });
          await Promise.all([refreshRack(), refreshBoard()]);
          render();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    }
    tbody.append(tr);
  });

  page.querySelector("#rack-filter").onchange = async (e) => {
    state.rackFilter = e.target.value;
    try {
      await refreshRack();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };

  const form = page.querySelector(".occupy-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const kettleId = Number(page.querySelector("#occ-kettle").value);
    const slotNo = Number(page.querySelector("#occ-slot").value);
    state.slotNo = page.querySelector("#occ-slot").value;
    try {
      await api("/api/rack/occupations", {
        method: "POST",
        body: JSON.stringify({ kettleId, slotNo }),
      });
      state.slotNo = "";
      await Promise.all([refreshRack(), refreshBoard()]);
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  if (!state.board) {
    app.append(el(`<div class="wrap">${esc(state.err) || "装载锅位…"}</div>`));
    return;
  }
  app.append(renderTopbar());
  const box = el(`<div class="wrap">
    ${
      state.view === "rack"
        ? `<section class="rackpage"></section>`
        : `<h1>${esc(state.board.workshop)}</h1>
           <p>${esc(state.board.alley)} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃</p>
           <div class="row"></div>
           <section class="drawer"></section>`
    }
    <p class="err">${esc(state.err)}</p>
  </div>`);
  if (state.view === "rack") {
    if (state.rack) renderRack(box);
    else box.querySelector(".rackpage").append(el(`<div>装载冷却架…</div>`));
  } else {
    renderBoard(box);
  }
  app.append(box);
}

if (state.ready) {
  refresh().catch((e) => {
    state.err = e.message;
    render();
  });
} else {
  render();
}

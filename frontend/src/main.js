import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };
const SLOT_MIN = 1;
const SLOT_MAX = 20;

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
  me: null,
  view: "board",
  board: null,
  racks: null,
  rackFilter: "",
  picked: null,
  peak: "96",
  occKettle: "",
  occSlot: "",
  err: "",
  rackErr: "",
  rackMsg: "",
  username: "admin",
  password: "123456",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function fmtTime(iso) {
  return iso ? iso.slice(0, 16).replace("T", " ") : "";
}

async function refreshBoard() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  }
}

async function refreshRack() {
  const qs = state.rackFilter ? `?kettle_id=${encodeURIComponent(state.rackFilter)}` : "";
  const data = await api(`/api/rack${qs}`);
  state.racks = data.racks;
}

async function goto(view) {
  state.view = view;
  state.err = "";
  state.rackErr = "";
  state.rackMsg = "";
  try {
    if (view === "board") await refreshBoard();
    else await refreshRack();
  } catch (ex) {
    if (view === "board") state.err = ex.message;
    else state.rackErr = ex.message;
  }
  render();
}

function renderLogin() {
  const box = el(`<div class="wrap">
    <h1>骨巷熬胶坊</h1>
    <p>一排熬锅作业台，原生页面，无前端框架。</p>
    <form autocomplete="off">
      <label>用户名
        <input name="u" autocomplete="off" value="${state.username}" />
      </label>
      <label>密码
        <input name="p" type="password" autocomplete="off" value="${state.password}" />
      </label>
      <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
      <button>登录</button>
    </form>
    <p class="err">${state.err}</p>
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
      state.me = data.user;
      state.ready = true;
      await goto("board");
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function topBar() {
  const isAdmin = state.me && state.me.role === "admin";
  const nav = el(`<nav class="topbar">
    <span class="brand">骨巷熬胶坊</span>
    <button class="navbtn ${state.view === "board" ? "active" : ""}" data-view="board">锅位作业台</button>
    <button class="navbtn ${state.view === "rack" ? "active" : ""}" data-view="rack">冷却架</button>
    <span class="who">${state.me ? state.me.username : ""}${isAdmin ? "（管理员）" : "（操作工）"}</span>
    <button class="logout" id="logout">退出</button>
  </nav>`);
  nav.querySelectorAll("[data-view]").forEach((b) => {
    b.onclick = () => goto(b.dataset.view);
  });
  nav.querySelector("#logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    location.reload();
  };
  return nav;
}

function renderBoard(box) {
  const view = el(`<div>
    <h1>${state.board.workshop}</h1>
    <p>${state.board.alley} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃；已出胶拨回冷锅须先占冷却架位</p>
    <div class="row"></div>
    <section class="drawer"></section>
    <p class="err">${state.err}</p>
  </div>`);
  box.append(view);
  const row = view.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const slotTag = k.rackSlotNo ? `<em class="slot-tag">架位 ${k.rackSlotNo}</em>` : "";
    const btn = el(`<button class="kettle ${k.status}"><strong>${k.code}</strong><span>${LABELS[k.status]}</span>${slotTag}</button>`);
    btn.onclick = () => {
      state.picked = k;
      state.err = "";
      render();
    };
    row.append(btn);
  });
  if (state.picked) renderDrawer(view.querySelector(".drawer"));
}

function renderDrawer(d) {
  const k = state.picked;
  const drawnNoSlot = k.status === "drawn" && !k.rackSlotNo;
  d.innerHTML = `<h3>${k.code} · ${LABELS[k.status]}</h3>
    <p>最近峰值：${k.latestPeakC ?? "无"} ℃ · ${k.cookCount} 次 · 冷却架位：${k.rackSlotNo ?? "未占位"}</p>
    <input id="peak" value="${state.peak}" />
    <button id="log">登记峰值</button>
    <div class="statusbtns">
      <button data-s="cold">冷锅</button>
      <button data-s="boiling">熬煮中</button>
      <button data-s="drawn">已出胶</button>
    </div>
    ${drawnNoSlot ? `<p class="err" id="coldblock">该锅尚未占用冷却架位，不能拨回冷锅；请先到「冷却架」占位。</p>` : ""}`;
  d.querySelector("#log").onclick = async () => {
    state.err = "";
    state.peak = d.querySelector("#peak").value;
    try {
      await api(`/api/kettles/${k.id}/cooks`, {
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
      // 已出胶拨回冷锅：先读未释放架位，没有则中文挡住。
      if (b.dataset.s === "cold" && k.status === "drawn" && !k.rackSlotNo) {
        state.err = "该锅尚未占用冷却架位，不能拨回冷锅；请先到「冷却架」占位。";
        render();
        return;
      }
      state.err = "";
      try {
        await api(`/api/kettles/${k.id}/status`, {
          method: "POST",
          body: JSON.stringify({ status: b.dataset.s }),
        });
        await refreshBoard();
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
  });
}

function kettleOptions(selected, drawnOnly = false) {
  return state.board
    ? state.board.kettles
        .filter((k) => !drawnOnly || k.status === "drawn")
        .map((k) => `<option value="${k.id}" ${String(k.id) === String(selected) ? "selected" : ""}>${k.code} · ${LABELS[k.status]}${k.rackSlotNo ? ` · 架位${k.rackSlotNo}` : ""}</option>`)
        .join("")
    : "";
}

function renderRack(box) {
  const isAdmin = state.me && state.me.role === "admin";
  const view = el(`<div>
    <h1>冷却架</h1>
    <p>架位号 ${SLOT_MIN}–${SLOT_MAX}；操作工可占位，释放仅管理员。已出胶的锅占一个未释放架位后才能拨回冷锅。</p>
    <p class="ok">${state.rackMsg}</p>
    <p class="err">${state.rackErr}</p>

    <form class="rackform" id="occform">
      <label>锅
        <select id="occKettle">${kettleOptions(state.occKettle, true)}</select>
      </label>
      <label>架位号
        <input id="occSlot" inputmode="numeric" value="${state.occSlot}" placeholder="1-20" />
      </label>
      <button id="occBtn">占位</button>
    </form>

    <div class="filterline">
      <label>按锅筛选
        <select id="rackFilter">
          <option value="">全部锅</option>
          ${kettleOptions(state.rackFilter)}
        </select>
      </label>
    </div>

    <table class="racktable">
      <thead><tr><th>架位号</th><th>锅</th><th>占用人</th><th>占用时刻</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
    ${!isAdmin ? `<p class="hint">当前为操作工：可占位，释放架位请找管理员。</p>` : ""}
  </div>`);
  box.append(view);

  const occKettle = view.querySelector("#occKettle");
  if (!state.occKettle) {
    const firstDrawn = state.board.kettles.find((k) => k.status === "drawn");
    if (firstDrawn) occKettle.value = String(firstDrawn.id);
  }
  view.querySelector("#occform").onsubmit = async (e) => {
    e.preventDefault();
    state.rackErr = "";
    state.rackMsg = "";
    state.occKettle = occKettle.value;
    state.occSlot = view.querySelector("#occSlot").value;
    try {
      await api("/api/rack", {
        method: "POST",
        body: JSON.stringify({ kettleId: Number(state.occKettle), slotNo: state.occSlot }),
      });
      state.rackMsg = "占位成功；该锅现在可拨回冷锅。";
      state.occSlot = "";
      await Promise.all([refreshBoard(), refreshRack()]);
      render();
    } catch (ex) {
      state.rackErr = ex.message;
      render();
    }
  };

  view.querySelector("#rackFilter").onchange = async (e) => {
    state.rackFilter = e.target.value;
    state.rackErr = "";
    try {
      await refreshRack();
      render();
    } catch (ex) {
      state.rackErr = ex.message;
      render();
    }
  };

  const tbody = view.querySelector(".racktable tbody");
  (state.racks || []).forEach((r) => {
    const tr = el(`<tr>
      <td>${r.slotNo}</td>
      <td>${r.kettleCode}</td>
      <td>${r.occupiedBy}</td>
      <td>${fmtTime(r.occupiedAt)}</td>
      <td></td>
    </tr>`);
    const cell = tr.lastElementChild;
    if (isAdmin) {
      const btn = el(`<button data-id="${r.id}">释放</button>`);
      btn.onclick = async () => {
        state.rackErr = "";
        state.rackMsg = "";
        try {
          await api(`/api/rack/${r.id}/release`, { method: "POST" });
          state.rackMsg = `架位 ${r.slotNo}（${r.kettleCode}）已释放。`;
          await Promise.all([refreshBoard(), refreshRack()]);
          render();
        } catch (ex) {
          state.rackErr = ex.message;
          render();
        }
      };
      cell.append(btn);
    } else {
      cell.textContent = "仅管理员";
    }
    tbody.append(tr);
  });
  if ((state.racks || []).length === 0) {
    tbody.append(el(`<tr><td colspan="5" class="hint">当前没有未释放的架位占用。</td></tr>`));
  }
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  app.append(topBar());
  const box = el(`<div class="wrap"></div>`);
  app.append(box);
  if (state.view === "rack") {
    if (!state.board) {
      refreshBoard()
        .then(() => renderRack(box))
        .catch((e) => box.append(el(`<p class="err">${e.message}</p>`)));
      return;
    }
    if (state.racks === null) {
      box.append(el(`<p>${state.rackErr || "装载冷却架…"}</p>`));
      return;
    }
    renderRack(box);
    return;
  }
  if (!state.board) {
    box.append(el(`<p>${state.err || "装载锅位…"}</p>`));
    return;
  }
  renderBoard(box);
}

async function boot() {
  if (!state.ready) {
    render();
    return;
  }
  try {
    state.me = await api("/api/auth/me");
    await refreshBoard();
    render();
  } catch (e) {
    if (String(e.message).includes("未登录")) {
      localStorage.removeItem(TOKEN_KEY);
      state.ready = false;
    } else {
      state.err = e.message;
    }
    render();
  }
}

boot();

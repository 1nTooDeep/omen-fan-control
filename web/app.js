const $ = (id) => document.getElementById(id);

const slider = $("slider");
const sliderVal = $("slider-val");
const pwmVal = $("pwm-val");
let dragging = false;
let toastTimer = null;

function showToast(msg, info = false) {
  const toast = $("toast");
  toast.textContent = msg;
  toast.classList.toggle("info", info);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
}

function tempClass(t) {
  if (t >= 85) return "hot";
  if (t >= 70) return "warm";
  return "";
}

function setTempColor(el, t) {
  el.classList.remove("hot", "warm");
  const cls = tempClass(t);
  if (cls) el.classList.add(cls);
}

function renderCores(cores) {
  const coresEl = $("cores");
  cores.forEach(([label, t], i) => {
    let cell = coresEl.children[i];
    if (!cell) {
      cell = document.createElement("span");
      cell.className = "core";
      const name = document.createElement("small");
      const val = document.createElement("b");
      cell.append(name, val);
      coresEl.appendChild(cell);
    }
    const [name, val] = cell.children;
    name.textContent = label
      .replace(/^Package(\s+id)?\s*/i, "Pkg ")
      .replace(/^Core\s*/i, "C");
    val.textContent = `${t}°`;
    cell.classList.toggle("warm", t >= 70 && t < 85);
    cell.classList.toggle("hot", t >= 85);
  });
  while (coresEl.children.length > cores.length) coresEl.lastChild.remove();
}

function activeMode(enable) {
  if (enable === "0") return "max";
  if (enable === "1") return "manual";
  return "auto";
}

function render(s) {
  $("board-badge").textContent = s.board ? `Board ${s.board}` : "OMEN";

  $("cpu-temp").textContent = s.cpu_temp;
  setTempColor($("cpu-temp"), s.cpu_temp);
  $("gpu-temp").textContent = s.gpu_temp || "–";
  $("fan1").textContent = s.fan1_rpm;
  $("fan2").textContent = s.fan2_rpm;

  renderCores(s.cores || []);

  $("hot-warning").hidden = s.cpu_temp < 85;

  const badge = $("board-badge");
  badge.classList.toggle("ok", s.driver_installed);
  badge.classList.toggle("off", !s.driver_installed);
  const modeText = { auto: "自动", max: "全速", manual: "手动" }[activeMode(s.enable)] || "未知";
  badge.textContent = `${badge.textContent} · 补丁驱动${s.driver_installed ? "已装" : "未装"} · ${modeText}`;

  document.querySelectorAll(".modes button").forEach((btn) => {
    const active = btn.dataset.mode === activeMode(s.enable);
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active);
  });

  $("btn-manual").disabled = !s.driver_installed;
  slider.disabled = !s.driver_installed;
  $("manual-note").hidden = s.driver_installed;

  if (!dragging && activeMode(s.enable) === "manual") {
    const percent = Math.round((s.manual_pwm / 255) * 100);
    slider.value = percent;
    updateSliderLabel(percent);
  }
}

function updateSliderLabel(percent) {
  sliderVal.textContent = `${percent}%`;
  pwmVal.textContent = Math.round((percent / 100) * 255);
  slider.style.setProperty("--fill", `${percent}%`);
}

async function poll() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
  } catch {
    $("board-badge").textContent = "服务未连接";
  }
}

async function applyMode(mode, value) {
  try {
    const res = await fetch("/api/fan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, value }),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || `HTTP ${res.status}`);
    } else if (mode === "manual") {
      showToast(`已设为手动 ${data.percent}%（PWM ${data.pwm}）`, true);
    } else {
      showToast(mode === "auto" ? "已切换为自动模式" : "已切换为全速模式", true);
    }
  } catch (err) {
    showToast(`请求失败: ${err.message}`);
  }
  poll();
}

document.querySelectorAll(".modes button").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.mode === "manual") {
      applyMode("manual", Number(slider.value));
    } else {
      applyMode(btn.dataset.mode);
    }
  });
});

slider.addEventListener("input", () => {
  dragging = true;
  updateSliderLabel(Number(slider.value));
});

slider.addEventListener("change", () => {
  dragging = false;
  applyMode("manual", Number(slider.value));
});

poll();
setInterval(poll, 1000);

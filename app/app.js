const STORAGE_KEY = "zk_quiz_state_v1";

/** 本地开发 app/ 用 ../data；GitHub Pages 部署到 docs/ 根目录用 data */
const DATA_BASE = (() => {
  const p = location.pathname.replace(/\\/g, "/");
  return /\/app(?:\/|$)/.test(p) ? "../data" : "data";
})();

const state = {
  bank: null,
  queue: [],
  index: 0,
  mode: "study",
  order: "sequential",
  scope: "all",
  answers: {},
  revealed: {},
  finished: false,
  wrongSet: new Set(),
};

const els = {
  title: document.getElementById("bank-title"),
  mode: document.getElementById("mode-select"),
  order: document.getElementById("order-select"),
  scope: document.getElementById("scope-select"),
  restart: document.getElementById("restart-btn"),
  progress: document.getElementById("stat-progress"),
  correct: document.getElementById("stat-correct"),
  wrong: document.getElementById("stat-wrong"),
  bankCount: document.getElementById("stat-bank"),
  progressBar: document.getElementById("progress-bar"),
  quizPanel: document.getElementById("quiz-panel"),
  resultPanel: document.getElementById("result-panel"),
  qIndex: document.getElementById("question-index"),
  qId: document.getElementById("question-id"),
  qBody: document.getElementById("question-body"),
  options: document.getElementById("options"),
  feedback: document.getElementById("feedback"),
  prev: document.getElementById("prev-btn"),
  next: document.getElementById("next-btn"),
  submitExam: document.getElementById("submit-exam-btn"),
  resultSummary: document.getElementById("result-summary"),
  wrongReview: document.getElementById("wrong-review"),
  reviewWrong: document.getElementById("review-wrong-btn"),
  backStudy: document.getElementById("back-study-btn"),
};

function loadPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (Array.isArray(data.wrongSet)) {
      state.wrongSet = new Set(data.wrongSet);
    }
  } catch (_) {
    /* ignore */
  }
}

function persistWrongSet() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ wrongSet: [...state.wrongSet] }),
  );
}

function enrichMathText(text) {
  if (!text) return "";
  // 已含 $ 或主要为 Unicode 符号/中文时直接显示
  if (text.includes("$") || /[\u4e00-\u9fffωζαβγτΔ∠∞±]/.test(text)) return text;
  return text
    .replace(/\\([a-zA-Z]+(?:_\{?[a-zA-Z0-9]+\}?)?)/g, "\\($1\\)")
    .replace(/\+\\\(infty\\\)/g, "\\(+\\infty\\)");
}

function renderSegments(segments, root, context = "stem") {
  root.innerHTML = "";
  segments.forEach((seg) => {
    if (seg.type === "text") {
      const span = document.createElement("span");
      span.innerHTML = enrichMathText(seg.content);
      root.appendChild(span);
    } else if (seg.type === "latex") {
      const span = document.createElement("span");
      span.innerHTML = seg.content.startsWith("$") ? seg.content : `$${seg.content}$`;
      root.appendChild(span);
    } else if (seg.type === "image") {
      const img = document.createElement("img");
      img.className = context === "stem" ? "formula-img stem-img" : "formula-img";
      img.src = `${DATA_BASE}/${seg.src}`;
      img.alt = seg.alt || "公式";
      img.loading = "lazy";
      img.title = "点击放大";
      img.addEventListener("click", (e) => {
        e.stopPropagation();
        openLightbox(img.src, img.alt);
      });
      root.appendChild(img);
    }
  });
}

function openLightbox(src, alt) {
  const box = document.getElementById("img-lightbox");
  const img = document.getElementById("lightbox-img");
  img.src = src;
  img.alt = alt || "放大公式";
  box.classList.remove("hidden");
  box.setAttribute("aria-hidden", "false");
}

function closeLightbox() {
  const box = document.getElementById("img-lightbox");
  box.classList.add("hidden");
  box.setAttribute("aria-hidden", "true");
  document.getElementById("lightbox-img").src = "";
}

function typeset(el) {
  if (window.MathJax?.typesetPromise) {
    return MathJax.typesetPromise([el]).catch(() => {});
  }
  return Promise.resolve();
}

function shuffle(arr) {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function buildQueue() {
  let list = [...state.bank.questions];
  if (state.scope === "wrong") {
    list = list.filter((q) => state.wrongSet.has(q.id));
  }
  if (state.order === "random") {
    list = shuffle(list);
  }
  return list;
}

function currentQuestion() {
  return state.queue[state.index] || null;
}

function goNextQuestion() {
  if (state.index >= state.queue.length - 1) return false;
  state.index += 1;
  renderQuestion();
  return true;
}

function hasAnsweredCurrent() {
  const q = currentQuestion();
  if (!q || state.finished) return false;
  return state.answers[q.id] !== undefined;
}

function isShortcutBlockedTarget() {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "SELECT" || tag === "INPUT" || tag === "TEXTAREA") return true;
  return !!el.closest(".toolbar");
}

function tryAdvanceAfterAnswer() {
  if (els.resultPanel.classList.contains("hidden") === false) return false;
  if (!hasAnsweredCurrent()) return false;
  return goNextQuestion();
}

function countStats() {
  let correct = 0;
  let wrong = 0;
  state.queue.forEach((q) => {
    const picked = state.answers[q.id];
    if (picked === undefined) return;
    if (picked === q.answer) correct += 1;
    else wrong += 1;
  });
  return { correct, wrong };
}

function updateStats() {
  const total = state.queue.length;
  const answered = Object.keys(state.answers).filter((id) =>
    state.queue.some((q) => String(q.id) === id),
  ).length;
  const { correct, wrong } = countStats();
  els.progress.textContent = `${answered}/${total}`;
  els.correct.textContent = String(correct);
  els.wrong.textContent = String(wrong);
  els.bankCount.textContent = String(state.wrongSet.size);
  els.progressBar.style.width = total ? `${(answered / total) * 100}%` : "0%";
}

function showFeedback(q, picked) {
  const ok = picked === q.answer;
  els.feedback.className = `feedback show ${ok ? "ok" : "bad"}`;
  els.feedback.innerHTML = ok
    ? `✓ 回答正确，答案是 <strong>${q.answer}</strong>`
    : `✗ 回答错误，你的选择 <strong>${picked}</strong>，正确答案是 <strong>${q.answer}</strong>`;
  if (!ok) {
    state.wrongSet.add(q.id);
    persistWrongSet();
  }
}

function renderQuestion() {
  const q = currentQuestion();
  if (!q) {
    els.qBody.textContent = state.scope === "wrong" ? "错题本为空，请先做错题或切换全部题目。" : "暂无题目";
    els.options.innerHTML = "";
    return;
  }

  els.qIndex.textContent = `第 ${state.index + 1} / ${state.queue.length} 题`;
  els.qId.textContent = `#${q.id}`;
  renderSegments(q.segments, els.qBody, "stem");

  const picked = state.answers[q.id];
  const revealed = state.revealed[q.id] || state.mode === "study";

  els.options.innerHTML = "";
  ["A", "B", "C", "D"].forEach((label) => {
    if (!q.options[label]) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "option";
    btn.dataset.label = label;

    const badge = document.createElement("span");
    badge.className = "label";
    badge.textContent = label;

    const content = document.createElement("div");
    content.className = "content";
    renderSegments(q.options[label], content, "option");

    btn.appendChild(badge);
    btn.appendChild(content);

    if (picked === label) btn.classList.add("selected");
    if (revealed && picked) {
      if (label === q.answer) btn.classList.add("correct");
      if (picked === label && picked !== q.answer) btn.classList.add("wrong");
    }

    btn.disabled = state.finished || (state.mode === "study" && !!picked);
    btn.addEventListener("click", () => chooseOption(q, label));
    els.options.appendChild(btn);
  });

  els.feedback.className = "feedback";
  els.feedback.innerHTML = "";
  if (state.mode === "study" && picked) {
    showFeedback(q, picked);
    if (state.index < state.queue.length - 1) {
      els.feedback.innerHTML += '<br><span style="opacity:.85;font-size:.9em">按空格或右键 → 下一题</span>';
    }
  }

  els.prev.disabled = state.index <= 0;
  els.next.disabled = state.index >= state.queue.length - 1;
  els.submitExam.classList.toggle("hidden", state.mode !== "exam" || state.finished);

  updateStats();
  typeset(els.qBody);
  typeset(els.options);
}

function chooseOption(q, label) {
  if (state.finished) return;
  if (state.answers[q.id] && state.mode === "study") return;

  state.answers[q.id] = label;
  if (state.mode === "study") {
    state.revealed[q.id] = true;
    showFeedback(q, label);
    updateStats();
    renderQuestion();
    return;
  }
  updateStats();
  renderQuestion();
}

function startSession(resetAnswers = true) {
  state.mode = els.mode.value;
  state.order = els.order.value;
  state.scope = els.scope.value;
  state.finished = false;

  if (resetAnswers) {
    state.answers = {};
    state.revealed = {};
    state.index = 0;
  }

  state.queue = buildQueue();
  els.quizPanel.classList.remove("hidden");
  els.resultPanel.classList.add("hidden");
  renderQuestion();
}

function submitExam() {
  state.finished = true;
  state.queue.forEach((q) => {
    state.revealed[q.id] = true;
  });

  const total = state.queue.length;
  const { correct, wrong } = countStats();
  const unanswered = total - correct - wrong;

  els.quizPanel.classList.add("hidden");
  els.resultPanel.classList.remove("hidden");
  els.resultSummary.innerHTML = `
    共 <strong>${total}</strong> 题，
    正确 <strong>${correct}</strong> 题，
    错误 <strong>${wrong}</strong> 题，
    未答 <strong>${unanswered}</strong> 题，
    得分 <strong>${total ? Math.round((correct / total) * 100) : 0}</strong> 分
  `;

  const wrongQs = state.queue.filter((q) => state.answers[q.id] !== q.answer);
  wrongQs.forEach((q) => state.wrongSet.add(q.id));
  persistWrongSet();

  if (!wrongQs.length) {
    els.wrongReview.innerHTML = "<p>全部正确，太棒了！</p>";
  } else {
    els.wrongReview.innerHTML = `
      <p>错题列表（已加入错题本）：</p>
      <ol class="wrong-list">
        ${wrongQs
          .map((q) => {
            const pick = state.answers[q.id] ?? "未答";
            return `<li>第 ${q.id} 题：你选择 ${pick}，正确答案 ${q.answer}</li>`;
          })
          .join("")}
      </ol>
    `;
  }
  updateStats();
}

async function init() {
  loadPersisted();
  const res = await fetch(`${DATA_BASE}/questions.json`);
  if (!res.ok) {
    throw new Error(`题库加载失败 HTTP ${res.status}`);
  }
  state.bank = await res.json();
  if (!state.bank?.questions?.length) {
    throw new Error("题库为空");
  }
  els.title.textContent = state.bank.title;

  els.mode.addEventListener("change", () => startSession(true));
  els.order.addEventListener("change", () => startSession(true));
  els.scope.addEventListener("change", () => startSession(true));
  els.restart.addEventListener("click", () => startSession(true));
  els.prev.addEventListener("click", () => {
    if (state.index > 0) {
      state.index -= 1;
      renderQuestion();
    }
  });
  els.next.addEventListener("click", () => {
    goNextQuestion();
  });
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" && e.key !== " ") return;
    if (isShortcutBlockedTarget()) return;
    if (!hasAnsweredCurrent()) return;
    e.preventDefault();
    tryAdvanceAfterAnswer();
  });
  els.quizPanel.addEventListener("contextmenu", (e) => {
    if (!hasAnsweredCurrent()) return;
    e.preventDefault();
    tryAdvanceAfterAnswer();
  });
  els.submitExam.addEventListener("click", submitExam);
  els.reviewWrong.addEventListener("click", () => {
    els.scope.value = "wrong";
    startSession(true);
  });
  els.backStudy.addEventListener("click", () => {
    els.scope.value = "all";
    startSession(true);
  });
  document.getElementById("img-lightbox").addEventListener("click", closeLightbox);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLightbox();
  });

  startSession(true);
}

init().catch((err) => {
  els.qBody.textContent = `加载失败：${err.message}。本地请运行 python scripts/serve.py；在线部署请确认已执行 python scripts/deploy_pages.py 并开启 GitHub Pages。`;
});

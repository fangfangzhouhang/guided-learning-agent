/* Guided Learning Agent — multi-page UI (hash routing).
   Pages: #/course  #/study/<conceptId>  #/chat  #/profile
   API shapes follow app/tutor.py: sessions return {session, question, stage};
   answers return {correct, feedback, explanation, question?, next_stage?, mastery?}. */
const $ = (s) => document.querySelector(s);
const student = () => $("#student").value.trim() || "ark";
async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

let courseData = null, concepts = {}, sessionId = null, curQ = null, curStage = "diagnose";
let selOpt = null, conf = null, chatLoadedFor = "";

/* ---------------- router ---------------- */
function route() {
  const h = location.hash || "#/course";
  const parts = h.replace("#/", "").split("/");
  const page = parts[0], param = parts[1];
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.querySelectorAll("[data-nav]").forEach(a =>
    a.classList.toggle("active", a.dataset.nav === page || (page === "study" && a.dataset.nav === "course")));
  if (page === "study" && param) { $("#view-study").classList.add("active"); startStudy(param); }
  else if (page === "chat") { $("#view-chat").classList.add("active"); loadChat(); }
  else if (page === "profile") { $("#view-profile").classList.add("active"); loadProfile(); }
  else { $("#view-course").classList.add("active"); loadCourse(); }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
$("#student").addEventListener("change", () => { chatLoadedFor = ""; route(); });

/* ---------------- status / offline diagnosis ---------------- */
async function loadStatus() {
  const pill = $("#statusPill");
  try {
    const s = await api("/api/status");
    if (s.llm_enabled) {
      pill.textContent = "AI 老师：在线（" + s.llm_model + "）";
      pill.className = "statuspill on";
      $("#chatDiag").style.display = "none";
    } else {
      pill.textContent = "AI 老师：离线模式";
      pill.className = "statuspill off";
      const d = $("#chatDiag");
      d.style.display = "block";
      d.innerHTML = "<b>离线原因自检（服务器实时结果）：</b><br>" +
        "· 项目根目录有 .env 文件吗：<b>" + (s.env_file_present ? "有" : "没有 ← 先把 .env.example 复制改名为 .env（别存成 .env.txt），放在有 README 的那一层") + "</b><br>" +
        "· key 读到了吗：<b>" + (s.key_configured ? "已读到" : "没读到 ← 打开 .env 检查 LLM_API_KEY= 后面有没有粘上 key") + "</b><br>" +
        "· 改完 .env 必须<b>重启服务</b>再刷新本页；若你打开的是手机演示卡，那个版本就固定是离线的，请用服务器版网址打开。";
    }
  } catch (e) { pill.textContent = "AI 老师：状态未知"; }
}

/* ---------------- course page ---------------- */
async function loadCourse() {
  if (!courseData) {
    courseData = await api("/api/course");
    $("#courseTitle").textContent = courseData.title || "三极管放大电路";
    concepts = {}; courseData.concepts.forEach(c => concepts[c.id] = c);
  }
  const prog = await api("/api/progress/" + encodeURIComponent(student()));
  const prof = await api("/api/profile/" + encodeURIComponent(student()));
  const total = courseData.concepts.length;
  const mastered = courseData.concepts.filter(c => (prog.mastery[c.id] || {}).status === "mastered").length;
  $("#courseBar").style.width = (total ? mastered / total * 100 : 0) + "%";
  $("#courseBarMeta").textContent = "已真正掌握 " + mastered + " / " + total + " 个知识点（以无提示独立测验全对为准）";
  const tip = $("#nextTip"), rec = prof.recommendation || {};
  if (rec.concept_id) {
    tip.style.display = "block";
    tip.innerHTML = "🎯 <b>下一步建议：</b>" + rec.reason + " —— <a href=\"#/study/" + rec.concept_id + "\">去学「" + (concepts[rec.concept_id] || {}).title + "」</a>";
  } else { tip.style.display = "block"; tip.textContent = "🏆 " + (rec.reason || "这一章都学过了"); }
  $("#conceptGrid").innerHTML = courseData.concepts.map((c, i) => {
    const m = prog.mastery[c.id] || {};
    const chip = m.status === "mastered" ? "<span class=\"chip mastered\">已掌握</span>"
      : m.status === "passed_with_help" ? "<span class=\"chip help\">靠提示通过 · 待复测</span>"
      : m.status === "needs_review" ? "<span class=\"chip review\">需要复习</span>"
      : "<span class=\"chip\">未开始</span>";
    const btn = m.status === "mastered" ? "再练一次" : (m.status ? "继续学习" : "开始学习");
    return "<div class=\"concept-card\"><div class=\"idx\"><span class=\"chip\">第 " + (i + 1) + " 站</span>" + chip + "</div>" +
      "<h3>" + c.title + "</h3><p>" + c.summary + "</p>" +
      "<button class=\"btn\" onclick=\"location.hash='#/study/" + c.id + "'\">" + btn + "</button></div>";
  }).join("");
}

/* ---------------- study page ---------------- */
async function startStudy(conceptId) {
  const c = concepts[conceptId];
  if (!c) { location.hash = "#/course"; return; }
  $("#studyTitle").textContent = c.title;
  $("#studyGoal").textContent = "要点：" + c.key_points.join("；");
  $("#qcard").innerHTML = "<p class=\"empty\">正在准备题目…</p>";
  const res = await post("/api/sessions", { student: student(), concept_id: conceptId });
  sessionId = res.session.id;
  curStage = res.stage || "diagnose";
  introThen(res);
}
function introThen(res) {
  stageUI(curStage, false);
  $("#qcard").innerHTML = "<p style=\"line-height:1.8;font-size:15px\">" + res.message + "</p>" +
    "<div class=\"row\"><button class=\"btn\" id=\"beginBtn\">开始第一题 →</button></div>";
  $("#beginBtn").onclick = () => showQuestion(res.question, curStage);
}
function stageUI(stage, done) {
  const order = ["diagnose", "guided", "test"];
  document.querySelectorAll("#stageSteps span").forEach(sp => {
    sp.className = done ? "done" : (sp.dataset.stage === stage ? "now" : (order.indexOf(sp.dataset.stage) < order.indexOf(stage) ? "done" : ""));
  });
}
function showQuestion(q, stage) {
  curQ = q; curStage = stage || curStage; selOpt = null; conf = null;
  stageUI(curStage, false);
  if (!q) { showDone(null); return; }
  let html = "<div class=\"prompt\">" + q.prompt + "</div>";
  html += "<div class=\"conflabel\">答题前先估一下把握（会被记录，用来抓“自以为会”）：</div><div class=\"confseg\">" +
    [1, 2, 3, 4, 5].map(n => "<button data-c=\"" + n + "\" onclick=\"pickConf(" + n + ")\">" + n + "</button>").join("") + "</div>";
  if (q.type === "mcq") {
    html += q.options.map((o, i) => "<button class=\"opt\" data-i=\"" + i + "\" onclick=\"pickOpt(" + i + ")\">" + "ABCDEFGH"[i] + ". " + o + "</button>").join("");
    html += "<div class=\"row\"><button class=\"btn\" id=\"submitBtn\" onclick=\"submitMCQ()\">提交答案</button>";
  } else if (q.type === "numeric") {
    html += "<input class=\"numin\" id=\"numin\" type=\"number\" step=\"any\" placeholder=\"输入数值" + (q.unit ? "（单位：" + q.unit + "）" : "") + "\">";
    html += "<div class=\"row\"><button class=\"btn\" id=\"submitBtn\" onclick=\"submitText()\">提交答案</button>";
  } else {
    html += "<textarea class=\"txtin\" id=\"txtin\" placeholder=\"用自己的话写清楚因果，老师会按要点点评\"></textarea>";
    html += "<div class=\"row\"><button class=\"btn\" id=\"submitBtn\" onclick=\"submitText()\">提交答案</button>";
  }
  if (curStage !== "test") html += "<button class=\"hintlink\" onclick=\"getHint()\">💡 看提示（会被记录）</button>";
  else html += "<span class=\"chip review\">独立测验 · 无提示</span>";
  html += "</div><div class=\"feedback\" id=\"fb\"></div>";
  $("#qcard").innerHTML = html;
}
function pickConf(n) { conf = n; document.querySelectorAll(".confseg button").forEach(b => b.classList.toggle("sel", +b.dataset.c === n)); }
function pickOpt(i) { selOpt = i; document.querySelectorAll(".opt").forEach(b => b.classList.toggle("sel", +b.dataset.i === i)); }
async function getHint() {
  try {
    const d = await post("/api/sessions/" + sessionId + "/hint", {});
    const fb = $("#fb");
    fb.className = "feedback ok";
    fb.innerHTML = "<div class=\"fb-title\">💡 提示 " + d.hint_level + "</div>" + d.hint + (d.demonstration ? "\n\n示范：" + d.demonstration : "");
  } catch (e) {
    const fb = $("#fb"); fb.className = "feedback bad"; fb.textContent = "这一步不能使用提示。";
  }
}
function submitMCQ() { if (selOpt === null) return alert("先选一个选项"); doSubmit({ option_index: selOpt }); }
function submitText() {
  if (curQ.type === "numeric") {
    const v = parseFloat($("#numin").value);
    if (Number.isNaN(v)) return alert("先填一个数值");
    doSubmit({ value: v });
  } else {
    const t = $("#txtin").value.trim();
    if (!t) return alert("先写下你的理解，写错也没关系");
    doSubmit({ text: t });
  }
}
async function doSubmit(body) {
  if (conf) body.confidence = conf;
  const btn = $("#submitBtn"); if (btn) btn.disabled = true;
  let d;
  try { d = await post("/api/sessions/" + sessionId + "/answer", body); }
  catch (e) { if (btn) btn.disabled = false; return alert("提交失败，请重试"); }
  const fb = $("#fb");
  fb.className = "feedback " + (d.correct ? "ok" : "bad");
  let html = "<div class=\"fb-title\">" + (d.correct ? "✅ 答对了" : "❌ 这次没对") + "</div>" + (d.feedback || "");
  if (d.judge_feedback) html += "\n\n老师点评：" + d.judge_feedback;
  if (d.explanation) html += "\n\n解析：" + d.explanation;
  if (d.calibration) html += "\n\n" + d.calibration;
  if (d.demonstration) html += "\n\n示范讲解：" + d.demonstration;
  if (d.question) html += "<div class=\"row\"><button class=\"btn\" id=\"nextBtn\">继续 →</button></div>";
  fb.innerHTML = html;
  if (d.question) {
    const nq = d.question, ns = d.next_stage || curStage;
    $("#nextBtn").onclick = () => showQuestion(nq, ns);
  } else if (d.mastery) {
    showDone(d.mastery);
  }
}
function showDone(mastery) {
  stageUI("test", true);
  const labels = { mastered: "🏆 真正掌握了", passed_with_help: "🟡 帮助下通过", needs_review: "🔴 需要复习" };
  const notes = {
    mastered: "独立测验全对、基本没靠提示——这一站过关，去课程页看看下一站。",
    passed_with_help: "测验答对了，但用了较多提示或有薄弱题。过段时间不看提示再自测一次，全对才算扎实。",
    needs_review: "测验没有全对，卡点已经记进你的画像。先去「问老师」把卡点问透，再回来复测。"
  };
  $("#qcard").innerHTML = "<div class=\"done-panel\"><div class=\"big\">" + (labels[mastery] || "本轮完成") + "</div>" +
    "<p>" + (notes[mastery] || "") + "</p>" +
    "<div class=\"row\" style=\"justify-content:center\"><button class=\"btn\" onclick=\"location.hash='#/course'\">返回课程</button>" +
    "<button class=\"btn ghost\" onclick=\"location.hash='#/chat'\">去问老师</button></div></div>";
}

/* ---------------- chat page ---------------- */
async function loadChat() {
  if (chatLoadedFor === student()) return;
  chatLoadedFor = student();
  const box = $("#chatlog"); box.innerHTML = "";
  try {
    const h = await api("/api/chat/" + encodeURIComponent(student()));
    if (!h.messages.length) addMsg("ai", "我是你的现电老师。哪里不懂直接问，我不会直接报答案，会带着你一步步想明白。");
    h.messages.forEach(m => addMsg(m.role === "user" ? "me" : "ai", m.content));
  } catch (e) { addMsg("ai", "我是你的现电老师。哪里不懂都可以问我。"); }
  box.scrollTop = box.scrollHeight;
}
function addMsg(who, text) {
  const d = document.createElement("div");
  d.className = "msg " + who; d.textContent = text;
  $("#chatlog").appendChild(d); $("#chatlog").scrollTop = 1e9;
}
async function sendChat() {
  const inp = $("#chatin"); const text = inp.value.trim(); if (!text) return;
  addMsg("me", text); inp.value = "";
  $("#chatsend").disabled = true;
  try {
    const d = await post("/api/chat", { student: student(), message: text });
    addMsg("ai", d.reply + (d.mode === "offline" ? "\n（当前是离线模板引导；页面顶部有离线原因自检）" : ""));
  } catch (e) { addMsg("ai", "网络有点问题，等下再问我一次。"); }
  $("#chatsend").disabled = false;
  loadStatus();
}
$("#chatsend").addEventListener("click", sendChat);
$("#chatin").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });

/* ---------------- profile page ---------------- */
async function loadProfile() {
  const p = await api("/api/profile/" + encodeURIComponent(student()));
  const state = { mastered: "✅ 已掌握", passed_with_help: "🟡 帮助下通过", needs_review: "🔴 待复习" };
  const entries = Object.entries(p.mastery || {});
  let html = "<div class=\"pcard\"><h3>📊 掌握情况</h3>" + (entries.length
    ? "<ul>" + entries.map(([cid, m]) => "<li>" + ((concepts[cid] || {}).title || cid) + "：" + (state[m.status] || m.status) +
      "（测验全对：" + (m.evidence.test_all_correct ? "是" : "否") + "，用提示 " + m.evidence.hints_used + " 次）</li>").join("") + "</ul>"
    : "<p class=\"empty\">还没有完成过任何知识点，先去课程页走完一节。</p>") + "</div>";
  html += "<div class=\"pcard\"><h3>⚠️ 你反复出现的误区</h3>" + ((p.misconceptions || []).length
    ? "<ul>" + p.misconceptions.map(m => "<li>出现 " + m.count + " 次：" + m.text + "</li>").join("") + "</ul>"
    : "<p class=\"empty\">暂时没有记录到反复误区，继续保持。</p>") + "</div>";
  html += "<div class=\"pcard\"><h3>🎯 下一步建议</h3><p>" + ((p.recommendation || {}).reason || "") +
    ((p.recommendation || {}).concept_id ? " —— <a href=\"#/study/" + p.recommendation.concept_id + "\">现在就去</a>" : "") + "</p></div>";
  $("#profileBody").innerHTML = html;
}

/* ---------------- boot ---------------- */
(async () => { await loadStatus(); await loadCourse(); route(); })();

const $ = (id) => document.getElementById(id);
let sessionId = null;
let currentQuestion = null;
let concepts = [];
const STAGE_CN = { diagnose: "诊断", guided: "引导练习", test: "独立测验（无提示）"};
const MASTERY_CN = { mastered: "✅ 已掌握", passed_with_help: "🟡 帮助下通过", needs_review: "🔴 待复习"};

async function api(path, opts) {
const res = await fetch(path, opts);
if (!res.ok) { const t = await res.text(); throw new Error(t);}
return res.json();
}
function student() { return $("student").value.trim() || "ark";}
function say(text, who = "tutor") {
const div = document.createElement("div");
div.className = "msg " + who;
div.textContent = text;
$("chat").appendChild(div);
$("chat").scrollTop = $("chat").scrollHeight;
}

async function loadCourse() {
const data = await api("/api/course");
concepts = data.concepts;
renderMap();
renderProgress();
}
function renderMap() {
const box = $("concepts"); box.innerHTML = "";
concepts.forEach((c, i) => {
const btn = document.createElement("button");
btn.className = "concept";
btn.innerHTML = `<span class="dot" id="dot-${c.id}"></span>${i + 1}. ${c.title}`;
btn.title = c.summary + (c.prerequisites.length? `\n先修：${c.prerequisites.join(", ")}`: "");
btn.onclick = () => startConcept(c);
box.appendChild(btn);
});
}
async function renderProgress() {
const data = await api("/api/progress/" + encodeURIComponent(student()));
const box = $("progress"); const entries = Object.entries(data.mastery);
document.querySelectorAll(".dot").forEach(d => d.textContent = "○");
if (!entries.length) { box.textContent = "还没有记录，先选一个知识点开始。"; return;}
box.innerHTML = "";
entries.forEach(([cid, m]) => {
const c = concepts.find(x => x.id === cid);
const line = document.createElement("div");
line.textContent = `${c? c.title: cid}：${MASTERY_CN[m.status] || m.status}`;
box.appendChild(line);
const dot = $("dot-" + cid);
if (dot) dot.textContent = m.status === "mastered"? "●": "◐";
});
}

async function startConcept(c) {
$("empty").classList.add("hidden");
$("chat").innerHTML = "";
say(`${c.summary}`, "tutor");
say(`要点：${c.key_points.join("；")}`, "tutor");
if (c.sources && c.sources.length) say(`资料来源：${c.sources.join("；")}`, "tutor");
const res = await api("/api/sessions", {
method: "POST", headers: { "Content-Type": "application/json"},
body: JSON.stringify({ student: student(), concept_id: c.id}),
});
sessionId = res.session.id;
say(res.message, "tutor");
showQuestion(res.question, res.stage);
}

function showQuestion(q, stage) {
currentQuestion = q;
$("question-box").classList.remove("hidden");
$("stage-label").textContent = "当前阶段：" + (STAGE_CN[stage] || stage);
$("question-text").textContent = q.prompt;
$("hint-box").classList.add("hidden"); $("hint-box").textContent = "";
$("hint-note").textContent = stage === "test"? "独立测验不能用提示": "";
$("hint-btn").disabled = stage === "test";
const box = $("options"); box.innerHTML = "";
q.options.forEach((text, idx) => {
const btn = document.createElement("button");
btn.className = "option"; btn.textContent = text;
btn.onclick = () => submitAnswer(idx);
box.appendChild(btn);
});
}

$("hint-btn").onclick = async () => {
if (!sessionId) return;
try {
const res = await api(`/api/sessions/${sessionId}/hint`, { method: "POST"});
const box = $("hint-box"); box.classList.remove("hidden");
box.textContent = "提示" + res.hint_level + "：" + res.hint + (res.demonstration? "\n\n" + res.demonstration: "");
$("hint-note").textContent = "已记录一次提示使用（会影响掌握判定）";
} catch (e) { $("hint-note").textContent = "这一步不能使用提示。";}
};

async function submitAnswer(idx) {
const conf = $("confidence").value;
say("我的回答：" + currentQuestion.options[idx], "me");
const res = await api(`/api/sessions/${sessionId}/answer`, {
method: "POST", headers: { "Content-Type": "application/json"},
body: JSON.stringify({ option_index: idx, confidence: conf? Number(conf): null}),
});
say((res.correct? "答对了。": "答错了。") + res.feedback, "tutor");
say("解析：" + res.explanation, "tutor");
if (res.calibration) say(res.calibration, "tutor");
if (res.demonstration) say(res.demonstration, "tutor");
if (res.question) showQuestion(res.question, res.next_stage);
else { $("question-box").classList.add("hidden"); renderProgress();}
}

$("student").addEventListener("change", renderProgress);
loadCourse();

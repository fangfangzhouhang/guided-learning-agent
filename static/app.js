const $ = (id) => document.getElementById(id);
let sessionId = null;
let currentQuestion = null;
let concepts = [];
const STAGE_CN = { diagnose: "诊断", guided: "引导练习", test: "独立测验（无提示）"};
const MASTERY_CN = { mastered: "✅ 已掌握", passed_with_help: "🟡 帮助下通过", needs_review: "🔴 待复习"};

async function api(path, opts) {
const res = await fetch(path, opts);
if (!res.ok) throw new Error(await res.text());
return res.json();
}
const student = () => $("student").value.trim() || "ark";
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json"}, body: JSON.stringify(body)});

/* tabs */
document.querySelectorAll(".tab").forEach(btn => {
btn.onclick = () => {
document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b === btn));
["learn", "chat", "profile"].forEach(t => $("tab-" + t).classList.toggle("hidden", t!== btn.dataset.tab));
if (btn.dataset.tab === "profile") loadProfile();
if (btn.dataset.tab === "chat") loadChatHistory();
};
});

/* ---------- course learning ---------- */
function say(text, who = "tutor") {
const div = document.createElement("div");
div.className = "msg " + who; div.textContent = text;
$("chatlog").appendChild(div);
$("chatlog").scrollTop = $("chatlog").scrollHeight;
}
async function loadCourse() {
const data = await api("/api/course");
concepts = data.concepts;
renderMap(); renderRecommend();
}
function renderMap() {
const box = $("concepts"); box.innerHTML = "";
concepts.forEach((c, i) => {
const btn = document.createElement("button");
btn.className = "concept";
btn.innerHTML = `<span class="dot" id="dot-${c.id}">○</span>${i + 1}. ${c.title}`;
btn.title = c.summary;
btn.onclick = () => startConcept(c);
box.appendChild(btn);
});
refreshDots();
}
async function refreshDots() {
const data = await api("/api/progress/" + encodeURIComponent(student()));
Object.entries(data.mastery).forEach(([cid, m]) => {
const dot = $("dot-" + cid);
if (dot) dot.textContent = m.status === "mastered"? "●": "◐";
});
}
async function renderRecommend() {
try {
const p = await api("/api/profile/" + encodeURIComponent(student()));
const box = $("recommend");
if (p.recommendation && p.recommendation.concept_id) {
box.classList.remove("hidden");
box.innerHTML = "";
const span = document.createElement("span"); span.textContent = "为你推荐：" + p.recommendation.reason + " ";
const btn = document.createElement("button"); btn.textContent = "开始";
btn.onclick = () => { const c = concepts.find(x => x.id === p.recommendation.concept_id); if (c) startConcept(c);};
box.append(span, btn);
}
} catch (e) { /* profile is optional decoration */}
}
async function startConcept(c) {
$("empty").classList.add("hidden");
$("chatlog").innerHTML = "";
say(`${c.summary}`);
say(`要点：${c.key_points.join("；")}`);
const res = await post("/api/sessions", { student: student(), concept_id: c.id});
sessionId = res.session.id;
say(res.message);
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
$("text-answer").classList.add("hidden");
$("numeric-input").classList.add("hidden");
$("explain-input").classList.add("hidden");
if (q.type === "mcq") {
q.options.forEach((text, idx) => {
const btn = document.createElement("button");
btn.className = "option"; btn.textContent = text;
btn.onclick = () => submitAnswer({ option_index: idx});
box.appendChild(btn);
});
} else {
$("text-answer").classList.remove("hidden");
if (q.type === "numeric") {
$("numeric-input").classList.remove("hidden");
$("unit-label").textContent = q.unit || "";
$("numeric-input").value = "";
} else {
$("explain-input").classList.remove("hidden");
$("unit-label").textContent = "";
$("explain-input").value = "";
}
}
}
$("submit-text").onclick = () => {
if (currentQuestion.type === "numeric") {
const v = parseFloat($("numeric-input").value);
if (Number.isNaN(v)) { $("hint-note").textContent = "请先输入一个数字。"; return;}
submitAnswer({ value: v});
} else {
const t = $("explain-input").value.trim();
if (!t) { $("hint-note").textContent = "先写一点你的思路，写错也没关系。"; return;}
submitAnswer({ text: t});
}
};
$("hint-btn").onclick = async () => {
if (!sessionId) return;
try {
const res = await post(`/api/sessions/${sessionId}/hint`, {});
const box = $("hint-box"); box.classList.remove("hidden");
box.textContent = "提示" + res.hint_level + "：" + res.hint + (res.demonstration? "\n\n" + res.demonstration: "");
$("hint-note").textContent = "已记录一次提示使用（会影响掌握判定）";
} catch (e) { $("hint-note").textContent = "这一步不能使用提示。";}
};
async function submitAnswer(payload) {
const label = payload.option_index!== undefined? currentQuestion.options[payload.option_index]
: payload.value!== undefined? String(payload.value): payload.text;
say("我的回答：" + label, "me");
const conf = $("confidence").value;
if (conf) payload.confidence = Number(conf);
const res = await post(`/api/sessions/${sessionId}/answer`, payload);
say((res.correct? "答对了。": "这次没对。") + res.feedback);
if (res.judge_feedback) say("老师点评：" + res.judge_feedback);
say("解析：" + res.explanation);
if (res.calibration) say(res.calibration);
if (res.demonstration) say(res.demonstration);
if (res.question) showQuestion(res.question, res.next_stage);
else { $("question-box").classList.add("hidden"); refreshDots(); renderRecommend();}
}

/* ---------- teacher chat ---------- */
function chatSay(text, who) {
const div = document.createElement("div");
div.className = "msg " + who; div.textContent = text;
$("teacher-chat").appendChild(div);
$("teacher-chat").scrollTop = $("teacher-chat").scrollHeight;
}
async function loadChatHistory() {
if ($("teacher-chat").dataset.loaded) return;
$("teacher-chat").dataset.loaded = "1";
try {
const data = await api("/api/chat/" + encodeURIComponent(student()));
if (!data.messages.length) chatSay("我是你的现电老师。哪里不懂都可以问我，我会先带你想一步，不会直接把答案甩给你。", "tutor");
data.messages.forEach(m => chatSay(m.content, m.role === "user"? "me": "tutor"));
} catch (e) { chatSay("我是你的现电老师。哪里不懂都可以问我。", "tutor");}
}
async function sendTeacher() {
const input = $("teacher-input");
const text = input.value.trim();
if (!text) return;
input.value = "";
chatSay(text, "me");
const thinking = document.createElement("div");
thinking.className = "msg tutor"; thinking.textContent = "老师正在想…";
$("teacher-chat").appendChild(thinking);
try {
const res = await post("/api/chat", { student: student(), message: text});
thinking.textContent = res.reply + (res.mode === "offline"? "": "");
} catch (e) { thinking.textContent = "网络有点问题，等下再问我一次。";}
}
$("teacher-send").onclick = sendTeacher;
$("teacher-input").addEventListener("keydown", e => { if (e.key === "Enter") sendTeacher();});

/* ---------- profile ---------- */
async function loadProfile() {
const box = $("profile-box");
box.textContent = "正在加载你的学习画像…";
const p = await api("/api/profile/" + encodeURIComponent(student()));
box.innerHTML = "";
const mk = (tag, text) => { const el = document.createElement(tag); el.textContent = text; box.appendChild(el); return el;};
mk("h3", "掌握情况");
const entries = Object.entries(p.mastery);
if (!entries.length) mk("p", "还没有完成过任何知识点。先去课程学习里走完一节吧。");
entries.forEach(([cid, m]) => {
const c = concepts.find(x => x.id === cid);
mk("p", `${c? c.title: cid}：${MASTERY_CN[m.status] || m.status}（测验全对：${m.evidence.test_all_correct? "是": "否"}，用提示 ${m.evidence.hints_used} 次）`);
});
mk("h3", "你反复出现的误区");
if (!p.misconceptions.length) mk("p", "暂时没有记录到反复误区。");
p.misconceptions.forEach(m => mk("p", `×${m.count}：${m.text}`));
mk("h3", "下一步建议");
mk("p", p.recommendation.reason);
}

$("student").addEventListener("change", () => { refreshDots(); renderRecommend(); delete $("teacher-chat").dataset.loaded; $("teacher-chat").innerHTML = "";});
loadCourse();

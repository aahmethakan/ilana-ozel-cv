let sessionId;
let jobTitle = "";
let currentDraft = null; let currentCoverLetter = null;
const SESSION_STORAGE_KEY = "ilana-ozel-cv.session-id";
const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[character]));
const dimensionLabel = { completeness: "Kapsam", evidence: "Kanıt", structure: "Düzen", ats_readiness: "ATS okunabilirliği" };
const jobStatusLabel = { matched: "Eşleşti", partial: "Kısmi eşleşme", not_evidenced: "CV'de kanıt bulunamadı", not_evaluable: "Güvenle değerlendirilemedi" };
const jobImportanceLabel = { required: "Zorunlu", preferred: "Tercih edilen", unknown: "Belirsiz" };
const categoryLabel = { metric: "Ölçülebilir sonuç", tool: "Araç / teknoloji", certification: "Sertifika", language: "Dil", leadership: "Liderlik", project_management: "Proje yönetimi", skill: "Beceri" };
const findingText = {
  contact_details: "İletişim bilgileri mevcut.", contact_details_missing: "İletişim bilgileri eksik.",
  work_history: "İş geçmişi yapılandırılmış.", work_history_missing: "İş geçmişi eksik.",
  role_details: "Rollerde unvan, şirket ve tarih bilgisi mevcut.", role_details_missing: "Bazı rollerde unvan, şirket veya tarih bilgisi eksik.",
  education: "Eğitim bilgisi mevcut.", education_missing: "Eğitim bilgisi eksik.",
  skills_or_tools: "Açık beceri veya araç bilgisi mevcut.", skills_or_tools_missing: "Açık beceri veya araç bilgisi eksik.",
  languages: "Dil bilgisi mevcut.", languages_missing: "Dil ve seviye bilgisi eksik.",
  project_or_publication_context: "Proje veya yayın bağlamı mevcut.", project_or_publication_context_missing: "Ayrı proje veya yayın bağlamı bulunmuyor.",
  role_evidence_coverage: "Her rol için destekleyici kanıt mevcut.", role_evidence_coverage_missing: "Bir veya daha fazla rol için destekleyici kanıt eksik.",
  work_fact_evidence: "Deneyim maddeleri sorumluluk kanıtı sağlıyor.", work_fact_evidence_missing: "İş geçmişine bağlı sorumluluk kanıtı yok.",
  explicit_metrics: "Ölçülebilir sonuç kanıtı mevcut.", no_structured_metrics: "Ölçülebilir sonuç kanıtı sınırlı.",
  role_tool_evidence: "Araçlar veya teknik beceriler deneyimle ilişkilendirilmiş.", no_role_tool_evidence: "Araçlar veya teknik beceriler rollere bağlanmamış.",
  project_evidence: "Projeler için destekleyici kanıt mevcut.", project_evidence_missing: "Projeler için destekleyici kanıt yok.",
  skills_breadth: "Okunabilir bir beceri çeşitliliği mevcut.", skills_breadth_missing: "Açık beceri veya araç çeşitliliği sınırlı.",
  evidence_depth: "Deneyim kanıtlarının derinliği yeterli.", evidence_depth_missing: "Deneyim kanıtlarının derinliği sınırlı.",
  machine_readable_text: "Makine tarafından okunabilir metin mevcut.", machine_readable_text_missing: "Makine tarafından okunabilir metin yok.",
  recognized_sections: "Açık bölüm yapısı mevcut.", recognized_sections_missing: "Standart bölüm başlıkları sınırlı.",
  bullet_structure: "Madde yapısı taranabilirliği artırıyor.", bullet_structure_missing: "Sorumluluk ve sonuç maddeleri sınırlı.",
  chronological_structure: "Deneyim bölümü kronolojik okumayı destekliyor.", chronological_structure_missing: "Deneyim kronolojisi açık değil.",
  no_structural_ambiguity: "Çözümlenmemiş yapısal belirsizlik algılanmadı.", unresolved_document_evidence: "Bazı içerikler yapısal olarak belirsiz.",
  ats_machine_readable: "Metin ATS tarafından okunabilir.", ats_machine_readable_missing: "Belge ATS için okunabilir metin içermiyor.",
  ats_standard_headings: "Standart ATS başlıkları mevcut.", ats_standard_headings_missing: "Deneyim, eğitim ve beceri başlıkları eksik olabilir.",
  ats_contact: "İletişim bölümü tanınabilir.", ats_contact_missing: "Tanınabilir iletişim bölümü bulunmuyor.",
  ats_experience: "Deneyim bölümü ATS tarafından tanınabilir.", ats_experience_missing: "Deneyim bölümü tanınamıyor.",
  ats_education: "Eğitim bölümü ATS tarafından tanınabilir.", ats_education_missing: "Eğitim bölümü tanınamıyor.",
  ats_skills: "Beceri bölümü ATS tarafından tanınabilir.", ats_skills_missing: "Beceri bölümü tanınamıyor.",
};

function status(message, type = "") { el("status").textContent = message; el("status").className = type; }
async function loadPublicReleaseInfo() {
  try {
    const response = await fetch("/api/v1/about");
    if (!response.ok) return;
    const info = await response.json();
    el("copyright-holder").textContent = info.copyright_holder || "AHA";
    el("release-version").textContent = info.version ? ` · v${info.version}` : "";
    const sourceLink = el("source-code-link");
    if (info.source_code_url) {
      sourceLink.href = info.source_code_url;
      sourceLink.hidden = false;
      el("source-code-status").hidden = true;
    }
  } catch (_) {
    // License and third-party links remain available if the release-info request fails.
  }
}
function generationMessage(message = "", type = "") { el("generation-message").textContent = message; el("generation-message").className = `note ${type}`; }
function apiMessage(payload, fallback) { return payload?.error?.message || payload?.detail?.message || fallback; }
function resetGenerationUI() { el("generation-review").hidden = true; el("generation-review").innerHTML = ""; currentCoverLetter = null; el("cover-letter-area").hidden = true; el("cover-letter-result").innerHTML = ""; el("generate-cover-letter").disabled = true; el("download-cover-docx").disabled = true; el("download-cover-pdf").disabled = true; el("quality-area").hidden = true; el("quality-result").innerHTML = ""; el("quality-cv").disabled = true; el("validation-area").hidden = true; el("validation-result").innerHTML = ""; el("validate-cv").disabled = true; generationMessage(); }
function enableGenerationUI() { el("generation-area").hidden = false; el("generate-review").disabled = false; resetGenerationUI(); }
function invalidateGenerationUI() { resetGenerationUI(); el("generate-review").disabled = true; generationMessage("CV veriniz değişti. Taslak oluşturmak için CV'nizi yeniden analiz edin.", "error"); }
function list(items, render = (item) => item) { return items?.length ? `<ul class="facts">${items.map((item) => `<li>${render(item)}</li>`).join("")}</ul>` : "<p class=\"note\">Gösterilecek veri yok.</p>"; }
function chips(items) { return items?.length ? `<div class="chips">${items.map((item) => `<span>${esc(item)}</span>`).join("")}</div>` : ""; }
function dateText(value) { if (!value) return ""; if (typeof value === "string") return value; return [value.month, value.year].filter(Boolean).join("/"); }
function range(item) { const start = dateText(item.start_date); const end = item.is_current ? "Devam ediyor" : dateText(item.end_date) || (item.date_range_open ? "Tarih aralığı açık" : ""); return [start, end].filter(Boolean).join(" – "); }

function profile(profileData) {
  const work = profileData.work_experiences?.map((item) => {
    const facts = item.facts?.slice(0, 4) || [];
    const context = [...facts.flatMap((fact) => [...(fact.tools || []), ...(fact.skills || [])]), ...facts.flatMap((fact) => (fact.metrics || []).map((metric) => `${metric.value ?? ""}${metric.unit ?? ""}`))];
    return `<article class="card work-card"><h3>${esc(item.title)} <span>· ${esc(item.company)}</span></h3><p class="note">${esc(range(item))}</p>${list(facts, (fact) => esc(fact.statement))}${chips([...new Set(context)].filter(Boolean))}</article>`;
  });
  const education = profileData.education?.map((item) => `<div class="card"><strong>${esc([item.degree, item.field_of_study].filter(Boolean).join(" · ") || item.institution)}</strong><p class="note">${esc(item.institution)}${range(item) ? ` · ${esc(range(item))}` : ""}</p></div>`);
  const groups = [
    ["Kişisel Bilgiler", [profileData.full_name, profileData.headline, profileData.contact?.email?.value, profileData.contact?.phone?.value].filter(Boolean)],
    ["İş Deneyimleri", work, true], ["Eğitim", education, true],
    ["Beceriler", profileData.skills?.map((item) => item.statement), false, true], ["Araçlar / Teknolojiler", profileData.tools?.map((item) => item.statement), false, true],
    ["Diller", profileData.languages?.map((item) => [item.language, item.proficiency].filter(Boolean).join(" · "))],
    ["Sertifikalar", profileData.certifications?.map((item) => item.name)], ["Projeler", profileData.projects?.map((item) => [item.name, item.role].filter(Boolean).join(" · "))],
    ["Yayınlar", profileData.publications?.map((item) => item.title)],
  ];
  el("profile").innerHTML = groups.filter(([, items]) => items?.length).map(([title, items, cards, chipList]) => `<section class="profile-group"><h3>${title}</h3>${cards ? items.join("") : chipList ? chips(items) : list(items, esc)}</section>`).join("") || "<p class=\"note\">Yapılandırılmış profil verisi bulunamadı.</p>";
}

function quality(data) {
  const unique = [...new Map((data.findings || []).map((item) => [item.code, item])).values()];
  const improvements = unique.filter((item) => item.severity !== "info");
  el("quality").innerHTML = `<div class="score">${data.overall_score} / 100</div><div class="dimension-grid">${data.dimensions.map((item) => `<div class="card"><strong>${dimensionLabel[item.dimension] || item.dimension}</strong><br>${item.score} / ${item.max_score}</div>`).join("")}</div><h3>Öne çıkanlar</h3>${list(unique.filter((item) => item.score_impact > 0).slice(0, 5), (item) => esc(findingText[item.code] || "Olumlu CV sinyali algılandı."))}<h3>Öncelikli geliştirme alanları</h3>${list(improvements.slice(0, 6), (item) => esc(findingText[item.code] || "Bu alan için CV kanıtı güçlendirilebilir."))}`;
}

function coachText(question) {
  const role = question.related_role ? `“${question.related_role}” rolü için ` : "";
  const prompts = { metric: "ölçülebilir bir sonuç paylaşabilir misiniz?", tool: "kullandığınız araç veya teknolojileri paylaşabilir misiniz?", certification: "eklemek istediğiniz bir sertifika var mı?", language: "dil ve seviyenizi paylaşabilir misiniz?", leadership: "ekip koordinasyonu veya liderlik deneyiminiz oldu mu?", project_management: "planladığınız veya yürüttüğünüz bir proje var mı?", skill: "eklemek istediğiniz bir beceri var mı?" };
  return `${role}${prompts[question.category] || "bu bilgiyi paylaşabilir misiniz?"}`;
}
function coachReason(question) { return `${categoryLabel[question.category] || "Bu bilgi"} CV’de henüz yeterince görünmüyor.${question.related_role ? ` Bağlam: ${question.related_role}.` : ""}`; }
function coach(target, questions) {
  el(target).innerHTML = questions?.length ? questions.map((question) => `<article class="question"><span class="label">${esc(categoryLabel[question.category] || "CV bilgisi")}</span><strong>${esc(question.question_text || coachText(question))}</strong><p class="note">${esc(question.reason || coachReason(question))}</p>${question.potential_impact ? `<p class="note"><strong>Olası etki:</strong> ${esc(question.potential_impact)}</p>` : ""}<textarea data-question="${esc(question.question_id)}" placeholder="Yanıtınızı yazın"></textarea><button data-save="${esc(question.question_id)}">Cevabı Kaydet</button><p class="note" data-output="${esc(question.question_id)}"></p></article>`).join("") : "<p class=\"note\">Bu aşamada ek soru yok.</p>";
}
document.addEventListener("click", (event) => { if (event.target.dataset.decision) saveDraftDecision(event.target); if (event.target.dataset.rewrite) rewriteDraftItem(event.target); if (event.target.dataset.coverDecision) saveCoverLetterDecision(event.target); if (event.target.dataset.coverRewrite) rewriteCoverLetterItem(event.target); if (event.target.dataset.continuation) resolveContinuationProposal(event.target); if (event.target.dataset.readiness) resolveReadinessItem(event.target); });
function renderReadiness(readiness) {
  const area = el("readiness-area"); const output = el("readiness-items"); const items = readiness?.items || [];
  if (!items.length || readiness?.status === "ready") { area.hidden = true; output.innerHTML = ""; return; }
  output.innerHTML = `<p class="note">Taslak oluşturmak için aşağıdaki kontrolü tamamlayın.</p>${items.map((item) => `<article class="question"><span class="label">CV kontrolü</span><p>${esc(item.message)}</p>${item.actions?.length ? item.actions.map((action) => `<button data-readiness="${esc(item.finding_id)}" data-readiness-action="${esc(action)}">${action === "REJECT" ? "Bu bilgiyi taslağa alma" : esc(action)}</button>`).join("") : "<p class=\"note\">Bu kontrol için güvenli bir otomatik işlem yoktur.</p>"}</article>`).join("")}`;
  area.hidden = false;
}
function renderCareerProfileReview(review) {
  const area = el("continuation-area"); const output = el("continuation-candidates");
  const items = review?.items || [];
  renderReadiness(review?.readiness);
  if (!items.length) { area.hidden = true; output.innerHTML = ""; return; }
  output.innerHTML = `<p class="note">${esc(String(review.summary?.needs_review_count || 0))} bilgi kontrol edilmeli · Profil durumu: ${review.summary?.profile_status === "PROFILE_READY" ? "Hazır" : "Kontrol gerekiyor"}</p>` + items.map((item) => `<article class="question" data-continuation-output="${esc(item.item_id)}"><span class="label">${esc(item.category)}</span><strong>${esc(item.title)}</strong><p>${esc(item.question)}</p><p><strong>${esc(item.proposed_value)}</strong></p><p class="note">${esc(item.reason)}</p><p class="note"><strong>Etkisi:</strong> ${esc(item.potential_impact)}</p><p class="note">Durum: ${esc(item.status)}</p>${item.actions.map((action) => `<button data-continuation="${esc(item.item_id)}" data-continuation-kind="${esc(item.category)}" data-continuation-action="${esc(action)}">${({ ACCEPT: "Kabul Et", CORRECT: "Düzelt", REJECT: "Reddet", LEAVE_UNRESOLVED: "Kararsız Bırak" })[action]}</button>`).join("")}</article>`).join("");
  area.hidden = false;
}
async function refreshCareerProfileReview() {
  if (!sessionId) return;
  const response = await fetch("/api/v1/cv/career-profile-review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) });
  if (response.ok) renderCareerProfileReview(await response.json());
}
async function resolveReadinessItem(button) {
  button.disabled = true;
  try {
    const response = await fetch("/api/v1/cv/readiness/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, finding_id: button.dataset.readiness, action: "reject" }) });
    const data = await response.json(); if (!response.ok) throw Error(apiMessage(data, "Bu kontrol işlenemedi."));
    renderCareerProfileReview(data.career_profile_review);
    if (data.job_results) { renderJobSummary(data.job_results); renderJobCoach(data.job_results.job_coach.questions); el("job-results").hidden = false; }
    resetGenerationUI(); el("generate-review").disabled = false;
    status("Belirsiz bilgi taslağa dahil edilmeyecek; CV bağlamı güncellendi.", "success");
  } catch (error) { status(error.message || "Bu kontrol işlenemedi.", "error"); button.disabled = false; }
}
async function resolveContinuationProposal(button) {
  let correction = null;
  if (button.dataset.continuationAction === "CORRECT") { correction = window.prompt("Doğru şirket adını yazın:"); if (correction === null) return; }
  button.disabled = true;
  try {
    const isContinuation = button.dataset.continuationKind === "WORK_EXPERIENCE_COMPANY";
    const response = await fetch(isContinuation ? "/api/v1/cv/continuation-candidate/resolve" : "/api/v1/cv/coach-candidate/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, candidate_id: button.dataset.continuation, action: isContinuation ? button.dataset.continuationAction : button.dataset.continuationAction.toLowerCase(), correction }) });
    const data = await response.json(); if (!response.ok) throw Error(apiMessage(data, "Öneri işlenemedi."));
    await refreshCareerProfileReview();
    resetGenerationUI(); el("job-results").hidden = true; el("generate-review").disabled = false;
    status("CV bağlamı güncellendi; iş ilanı analizini gerekirse yeniden çalıştırın.", "success");
  } catch (error) { status(error.message || "Öneri işlenemedi.", "error"); button.disabled = false; }
}
el("analyze-cv").onclick = async () => {
  const file = el("pdf").files[0]; const button = el("analyze-cv"); if (!file) return status("Lütfen bir PDF seçin.", "error");
  button.disabled = true; status("CV analiz ediliyor…");
  try { const form = new FormData(); form.append("file", file); const response = await fetch("/api/v1/cv/analyze", { method: "POST", body: form }); const data = await response.json(); if (!response.ok) throw Error(apiMessage(data, "CV analizi tamamlanamadı.")); sessionId = data.session_id; sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId); jobTitle = ""; profile(data.profile); quality(data.quality); coach("general-coach", data.coach.questions); renderCareerProfileReview(data.career_profile_review); el("cv-results").hidden = false; el("job-results").hidden = true; el("analyze-job").disabled = false; el("delete-session").disabled = false; enableGenerationUI(); status("CV analizi tamamlandı.", "success"); } catch (error) { status(error.message, "error"); } finally { button.disabled = false; }
};
function generationError(data) {
  const code = data?.error?.code || data?.detail?.code;
  return {
    analysis_session_not_found: "CV oturumu bulunamadı. Lütfen CV'nizi yeniden analiz edin.",
    unified_context_unavailable: "CV veriniz güncel değil. Taslak oluşturmak için CV'nizi yeniden analiz edin.",
    targeted_job_state_missing: "İlana özel CV oluşturmak için önce iş ilanını analiz etmelisiniz.",
    generation_readiness_blocked: "CV'nizde taslak oluşturmak için gerekli doğrulanmış bilgiler henüz yeterli değil.",
    generation_readiness_needs_review: "CV'nizde önce gözden geçirilmesi gereken bilgiler var.",
  }[code] || "CV taslağı güvenli şekilde oluşturulamadı. Lütfen daha sonra tekrar deneyin.";
}
function renderGenerationReview(payload) {
  currentDraft = payload;
  const review = payload.review;
  const work = review.work_entries || [];
  const skills = review.skills || [];
  const education = review.education || [];
  const hasExportableContent = Boolean(work.length || skills.length || education.length);
  el("download-docx").disabled = !hasExportableContent;
  el("download-pdf").disabled = !hasExportableContent;
  el("validation-area").hidden = false;
  el("validate-cv").disabled = false;
  el("quality-area").hidden = false;
  el("quality-cv").disabled = false;
  const targeted = review.mode === "targeted";
  el("cover-letter-area").hidden = !targeted;
  el("generate-cover-letter").disabled = !targeted || !hasExportableContent;
  const title = targeted ? "İlana Özel CV Taslağı" : "Genel CV Taslağı";
  const job = targeted && jobTitle ? ` <span>· ${esc(jobTitle)}</span>` : "";
  const workHtml = work.length ? work.map((item) => { const entry = payload.items.find((candidate) => candidate.section === "work_entry" && candidate.text === `${item.title} — ${item.company}`); const facts = (item.claims || []).map((claim) => { const fact = payload.items.find((candidate) => candidate.section === "work_fact" && candidate.text === claim.text); return `<li>${esc(claim.text)}${fact ? ` <button data-decision="${esc(fact.item_id)}" data-next="remove">Çıkar</button>` : ""}</li>`; }).join(""); return `<article class="card work-card"><h3>${esc(item.title)} <span>· ${esc(item.company)}</span></h3>${item.dates ? `<p class="note">${esc(item.dates)}</p>` : ""}${facts ? `<ul class="facts">${facts}</ul>` : ""}${entry ? `<button data-decision="${esc(entry.item_id)}" data-next="remove">Bu deneyimi çıkar</button>` : ""}</article>`; }).join("") : "<p class=\"note\">Bu taslakta seçili deneyim maddesi yok.</p>";
  const skillsHtml = skills.length ? skills.map((item) => { const reviewItem = payload.items.find((candidate) => candidate.text === item.text && candidate.section === "skill"); const change = reviewItem && payload.changes.find((candidate) => candidate.item_id === reviewItem.item_id); const beforeAfter = change?.change_type === "rewritten" ? `<p class="note"><strong>Orijinal:</strong> ${esc(change.original_text)}<br><strong>Yeniden yazılmış:</strong> ${esc(change.proposed_text)}<br>✓ Fact-safe · ✓ Wording improved</p>` : ""; return `<article class="card"><strong>${esc(item.text)}</strong>${beforeAfter}${reviewItem ? `<button data-rewrite="${esc(reviewItem.item_id)}">Yeniden Yaz</button><button data-decision="${esc(reviewItem.item_id)}" data-next="remove">CV'den çıkar</button>` : ""}</article>`; }).join("") : "<p class=\"note\">Bu taslakta seçili beceri yok.</p>";
  const educationHtml = education.length ? education.map((item) => { const entry = payload.items.find((candidate) => candidate.section === "education" && candidate.text.includes(item.institution)); return `<article class="card"><strong>${esc(item.qualification || item.institution)}</strong><p class="note">${esc(item.institution)}${item.dates ? ` · ${esc(item.dates)}` : ""}</p>${entry ? `<button data-decision="${esc(entry.item_id)}" data-next="remove">CV'den çıkar</button>` : ""}</article>`; }).join("") : "<p class=\"note\">Bu taslakta seçili eğitim kaydı yok.</p>";
  const removed = payload.items.filter((item) => item.decision === "remove");
  const removedHtml = removed.length ? `<h3>Taslaktan çıkarılanlar</h3>${removed.map((item) => `<article class="card"><span class="note">Bu bilgi yalnızca bu taslaktan çıkarıldı.</span><br><strong>${esc(item.text)}</strong><br><button data-decision="${esc(item.item_id)}" data-next="keep">Geri al</button></article>`).join("")}` : "";
  el("generation-review").innerHTML = `<p>6. TASLAK İNCELEME</p><h2>${title}${job}</h2><p class="note">Bu aşamada sistem yalnızca doğrulanmış bilgilerinizden oluşan deterministic bir taslak oluşturur.</p><div class="dimension-grid"><div class="card"><strong>Deneyim</strong><br>${work.length}</div><div class="card"><strong>Beceri</strong><br>${skills.length}</div><div class="card"><strong>Eğitim</strong><br>${education.length}</div></div><h3>Deneyim</h3>${workHtml}<h3>Öne Çıkan Beceriler</h3>${skillsHtml}<h3>Eğitim</h3>${educationHtml}${removedHtml}<p class="note">Bu bilgi doğrulanmış CV verilerinden oluşturuldu.</p>`;
  el("generation-review").hidden = false;
}
el("generate-review").onclick = async () => {
  const button = el("generate-review");
  if (!sessionId) return generationMessage("Önce CV'nizi analiz edin.", "error");
  const mode = document.querySelector('input[name="generation-mode"]:checked').value;
  button.disabled = true; resetGenerationUI(); generationMessage("CV taslağı hazırlanıyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, mode }) });
    const data = await response.json();
    if (!response.ok) throw data;
    renderGenerationReview(data); generationMessage("CV taslağı hazır.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
};

async function saveDraftDecision(button) {
  if (!currentDraft) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/v1/cv/generate/review/decision", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentDraft.draft_id, item_id: button.dataset.decision, decision: button.dataset.next }) });
    const data = await response.json();
    if (!response.ok) throw data;
    renderGenerationReview(data); generationMessage(button.dataset.next === "remove" ? "Bu bilgi yalnızca bu taslaktan çıkarıldı." : "Bilgi taslağa geri alındı.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
}

async function rewriteDraftItem(button) {
  if (!currentDraft) return;
  button.disabled = true; generationMessage("İyileştiriliyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/review/rewrite", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentDraft.draft_id, item_id: button.dataset.rewrite }) });
    const data = await response.json(); if (!response.ok) throw data;
    renderGenerationReview(data); generationMessage("İfade güvenli şekilde iyileştirildi.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
}

el("download-docx").onclick = async () => {
  if (!currentDraft) return;
  const button = el("download-docx"); button.disabled = true; generationMessage("Word belgesi hazırlanıyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/export/docx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentDraft.draft_id }) });
    if (!response.ok) throw await response.json();
    const blob = await response.blob(); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "CV.docx"; link.click(); URL.revokeObjectURL(link.href);
    generationMessage("Word belgesi indirildi.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
};

el("download-pdf").onclick = async () => {
  if (!currentDraft) return;
  const button = el("download-pdf"); button.disabled = true; generationMessage("PDF belgesi hazırlanıyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/export/pdf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentDraft.draft_id }) });
    if (!response.ok) throw await response.json();
    const blob = await response.blob(); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "CV.pdf"; link.click(); URL.revokeObjectURL(link.href);
    generationMessage("PDF belgesi indirildi.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
};

el("validate-cv").onclick = async () => {
  if (!currentDraft) return;
  const button = el("validate-cv"); button.disabled = true; generationMessage("CV kontrol ediliyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentDraft.draft_id }) });
    const data = await response.json(); if (!response.ok) throw data;
    const icon = { PASS: "✓", WARNING: "⚠", BLOCK: "✕" };
    const validators = data.validators.map((item) => `<li><strong>${esc(item.validator)}</strong> ${icon[item.status] || ""} ${esc(item.status)}</li>`).join("");
    const issues = data.issues.length ? `<h3>Notlar</h3><ul>${data.issues.map((item) => `<li>${esc(item.message)}</li>`).join("")}</ul>` : "<p>Kontrol edilecek sorun bulunamadı.</p>";
    el("validation-result").innerHTML = `<h2>CV Kontrolü: ${esc(data.overall_status)}</h2><ul>${validators}</ul>${issues}`;
    generationMessage(data.overall_status === "BLOCKED" ? "CV kontrolü engelleyici bulgular tespit etti." : "CV kontrolü tamamlandı.", data.overall_status === "BLOCKED" ? "error" : "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
};

el("quality-cv").onclick = async () => {
  if (!currentDraft) return;
  const button = el("quality-cv"); button.disabled = true; generationMessage("CV kalitesi hesaplanıyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/quality", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentDraft.draft_id }) });
    const data = await response.json(); if (!response.ok) throw data;
    const dimensions = data.dimensions.map((item) => `<li><strong>${esc(item.name)}</strong>: ${esc(String(item.score))} / ${esc(String(item.max_score))}</li>`).join("");
    const findings = data.improvement_opportunities.length ? `<h3>Geliştirme alanları</h3><ul>${data.improvement_opportunities.map((item) => `<li>${esc(item.message)}</li>`).join("")}</ul>` : "";
    el("quality-result").innerHTML = `<h2>CV Kalitesi: ${esc(String(data.score))} / 100</h2><ul>${dimensions}</ul>${findings}`;
    generationMessage("CV kalite değerlendirmesi tamamlandı.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
};

function renderCoverLetter(payload) {
  currentCoverLetter = payload;
  el("download-cover-docx").disabled = false; el("download-cover-pdf").disabled = false;
  const body = payload.body_sections.length ? `<h3>İlgili kanıtlar</h3><ul>${payload.body_sections.map((text) => `<li>${esc(text)}</li>`).join("")}</ul>` : "<p>Bu ilanla ilişkili güvenli kanıt seçilemedi.</p>";
  const removed = payload.items.filter((item) => item.decision === "remove");
  const controls = payload.items.map((item) => { const rewrite = item.rewrite; const rewriteInfo = rewrite ? `<p class="note"><strong>Orijinal:</strong> ${esc(rewrite.original_text)}<br><strong>İyileştirilmiş:</strong> ${esc(rewrite.rewritten_text)}<br>Fact-safe: ${rewrite.fact_safety === "safe" ? "Evet" : "Hayır"} · Wording: ${esc(rewrite.quality_status)}${rewrite.final_status === "rejected" ? " · Mevcut güvenli metin korundu." : ""}</p>` : ""; return `<li>${esc(item.text)} ${item.decision === "remove" ? `<button data-cover-decision="${esc(item.item_id)}" data-next="keep">Geri Al</button>` : `<button data-cover-rewrite="${esc(item.item_id)}">Yeniden Yaz</button><button data-cover-decision="${esc(item.item_id)}" data-next="remove">Çıkar</button>`}${rewriteInfo}</li>`; }).join("");
  el("cover-letter-result").innerHTML = `<h2>Ön Yazı</h2><p>${esc(payload.opening)}</p>${body}<p>${esc(payload.closing)}</p>${controls ? `<h3>Seçili maddeler</h3><ul>${controls}</ul>` : ""}${removed.length ? `<p class="note">Çıkarılan maddeler ön yazıya dahil edilmez.</p>` : ""}`;
}

el("generate-cover-letter").onclick = async () => {
  const button = el("generate-cover-letter"); button.disabled = true; generationMessage("Ön yazı hazırlanıyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/cover-letter", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, mode: "targeted" }) });
    const data = await response.json(); if (!response.ok) throw data;
    renderCoverLetter(data); generationMessage("Ön yazı taslağı hazır.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
};

async function saveCoverLetterDecision(button) {
  if (!currentCoverLetter) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/v1/cv/generate/cover-letter/decision", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentCoverLetter.draft_id, item_id: button.dataset.coverDecision, decision: button.dataset.next }) });
    const data = await response.json(); if (!response.ok) throw data;
    renderCoverLetter(data); generationMessage(button.dataset.next === "remove" ? "Madde ön yazıdan çıkarıldı." : "Madde ön yazıya geri alındı.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
}

async function rewriteCoverLetterItem(button) {
  if (!currentCoverLetter) return;
  button.disabled = true; generationMessage("Ön yazı ifadesi güvenli şekilde iyileştiriliyor...");
  try {
    const response = await fetch("/api/v1/cv/generate/cover-letter/rewrite", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentCoverLetter.draft_id, item_id: button.dataset.coverRewrite }) });
    const data = await response.json(); if (!response.ok) throw data;
    renderCoverLetter(data); generationMessage("Ön yazı ifadesi güvenli metin korunarak güncellendi.", "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
}

async function downloadCoverLetter(format) {
  if (!currentCoverLetter) return;
  const button = el(format === "docx" ? "download-cover-docx" : "download-cover-pdf"); button.disabled = true; generationMessage(`${format.toUpperCase()} dosyası hazırlanıyor...`);
  try {
    const response = await fetch(`/api/v1/cv/generate/cover-letter/export/${format}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, draft_id: currentCoverLetter.draft_id }) });
    if (!response.ok) throw await response.json();
    const blob = await response.blob(); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = format === "docx" ? "Cover_Letter.docx" : "Cover_Letter.pdf"; link.click(); URL.revokeObjectURL(link.href);
    generationMessage(`${format.toUpperCase()} dosyası indirildi.`, "success");
  } catch (error) { generationMessage(generationError(error), "error"); } finally { button.disabled = false; }
}

el("download-cover-docx").onclick = () => downloadCoverLetter("docx");
el("download-cover-pdf").onclick = () => downloadCoverLetter("pdf");

async function submitCoachAnswer(button) {
  const questionId = button.dataset.save;
  const output = document.querySelector(`[data-output="${CSS.escape(questionId)}"]`);
  const answerText = document.querySelector(`[data-question="${CSS.escape(questionId)}"]`).value;
  button.disabled = true;
  try {
    const response = await fetch("/api/v1/cv/coach-answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, question_id: questionId, answer_text: answerText }) });
    const data = await response.json();
    if (!response.ok) throw Error(apiMessage(data, "Cevap işlenemedi."));
    if (data.candidate && data.candidate_id) {
      output.innerHTML = `<strong>Önerilen bilgi:</strong> ${esc(data.candidate.proposed_statement)}<br><span>Kaynak: yanıtınız · Onay bekliyor</span><br><button data-candidate="${esc(data.candidate_id)}" data-action="accept">Kabul Et</button><button data-candidate="${esc(data.candidate_id)}" data-action="correct">Düzelt</button><button data-candidate="${esc(data.candidate_id)}" data-action="reject">Reddet</button>`;
      await refreshCareerProfileReview();
    } else output.textContent = "Yanıt kaydedildi.";
  } catch (error) { output.textContent = error.message; } finally { button.disabled = false; }
}

async function resolveCoachProposal(button) {
  let correction = null;
  if (button.dataset.action === "correct") { correction = window.prompt("Düzeltilmiş bilgiyi yazın:"); if (!correction) return; }
  const response = await fetch("/api/v1/cv/coach-candidate/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, candidate_id: button.dataset.candidate, action: button.dataset.action, correction }) });
  const data = await response.json();
  if (!response.ok) throw Error(apiMessage(data, "Öneri işlenemedi."));
  button.closest("[data-output]").textContent = data.status === "promoted" ? "Bilgi onaylandı. Kariyer bağlamı güncellendi; yeni bir taslak oluşturabilirsiniz." : "Öneri reddedildi; CV değişmedi.";
  if (data.status === "promoted") {
    if (data.profile) profile(data.profile);
    if (data.career_profile_review) renderCareerProfileReview(data.career_profile_review);
    if (data.job_results) { renderJobSummary(data.job_results); renderJobCoach(data.job_results.job_coach.questions); el("job-results").hidden = false; }
    resetGenerationUI(); el("generate-review").disabled = false;
  }
}

document.addEventListener("click", (event) => {
  if (event.target.dataset.save) { event.stopImmediatePropagation(); submitCoachAnswer(event.target); }
  if (event.target.dataset.candidate) resolveCoachProposal(event.target).catch(error => status(error.message, "error"));
}, true);

// Keep the UI state aligned with the dependency between CV, job analysis, and generation.
const selectedFileNote = document.createElement("p");
selectedFileNote.id = "selected-file";
selectedFileNote.className = "note";
el("pdf").after(selectedFileNote);
const targetedMode = document.querySelector('input[name="generation-mode"][value="targeted"]');
const targetedModeNote = document.createElement("p");
targetedModeNote.className = "note";
el("generation-mode").after(targetedModeNote);
el("pdf").addEventListener("change", () => {
  const file = el("pdf").files[0];
  selectedFileNote.textContent = file ? `Seçilen dosya: ${file.name}` : "";
});
new MutationObserver(() => {
  const jobIsReady = !el("job-results").hidden;
  if (targetedMode) {
    targetedMode.disabled = !jobIsReady;
    targetedMode.title = jobIsReady ? "" : "İlana Özel CV için önce iş ilanını analiz edin.";
  }
  targetedModeNote.textContent = jobIsReady ? "İlana özel taslak için iş ilanı analizi hazır." : "İlana Özel CV için önce iş ilanı metnini analiz edin.";
}).observe(el("job-results"), { attributes: true, attributeFilter: ["hidden"] });
if (targetedMode) targetedMode.disabled = true;
targetedModeNote.textContent = "İlana Özel CV için önce iş ilanı metnini analiz edin.";

const jobCategoryLabel = { education: "Eğitim", experience: "Deneyim", skill: "Beceri", tool: "Araç / sistem", language: "Dil", certification: "Sertifika", other: "Diğer" };

function renderRequirementCard(result) {
  const requirement = result.requirement || {};
  return `<article class="requirement ${esc(result.status || "not_evaluable")}"><h3>${esc(requirement.text || "Gereksinim")}</h3><div class="chips"><span>${esc(jobImportanceLabel[requirement.importance] || "Belirsiz")}</span><span>${esc(jobStatusLabel[result.status] || result.status || "Bilinmeyen durum")}</span><span>${esc(jobCategoryLabel[requirement.category] || requirement.category || "Diğer")}</span></div>${result.explanation ? `<p class="note">${esc(result.explanation)}</p>` : ""}</article>`;
}

function renderJobSummary(data) {
  const profile = data.job_analysis.profile;
  jobTitle = profile.title || "";
  const score = data.job_score;
  el("job-analysis").innerHTML = `<div class="job-summary"><h3>${esc(profile.title || "Rol belirtilmedi")}</h3><div class="dimension-grid"><div class="card"><strong>Gereksinimler</strong><br>${profile.requirements?.length || 0}</div><div class="card"><strong>Sorumluluklar</strong><br>${profile.responsibilities?.length || 0}</div><div class="card"><strong>İş uyumu puanı</strong><br>${score.match_score ?? "—"} / 100</div><div class="card"><strong>Değerlendirme kapsamı</strong><br>${score.evaluation_coverage ?? "—"}%</div></div><p class="note">Kapsam, CV'deki mevcut bilgilerle güvenle değerlendirilebilen gereksinimlerin oranıdır.</p><h3>Sorumluluklar</h3>${list(profile.responsibilities, item => esc(item.text))}</div>`;
  el("job-score").innerHTML = `<div class="score">${score.match_score ?? "—"} / 100</div><p class="note">Değerlendirme kapsamı: ${score.evaluation_coverage ?? "—"}%</p>`;
  el("requirements").innerHTML = data.job_match.requirement_results?.length ? data.job_match.requirement_results.map(renderRequirementCard).join("") : "<p class=\"note\">Yapılandırılmış gereksinim bulunamadı.</p>";
}

function renderJobCoach(items) {
  el("job-coach").innerHTML = items?.length ? items.map((item) => { const q = item.question; return `<article class="question"><span class="label">İlana özel Coach</span><strong>${esc(q.question_text)}</strong>${item.requirement_text ? `<p class="note">İlgili gereksinim: ${esc(item.requirement_text)}</p>` : ""}<p class="note">${esc(q.reason)}</p>${q.potential_impact ? `<p class="note"><strong>Olası etki:</strong> ${esc(q.potential_impact)}</p>` : ""}<textarea data-question="${esc(q.question_id)}" placeholder="Yanıtınızı yazın"></textarea><button data-save="${esc(q.question_id)}">Cevabı Kaydet</button><p class="note" data-output="${esc(q.question_id)}"></p></article>`; }).join("") : "<p class=\"note\">Bu ilan için ek Coach sorusu yok.</p>";
}

el("analyze-job").onclick = async () => {
  const jobText = el("job-text").value; const button = el("analyze-job");
  if (!jobText.trim()) return status("Lütfen iş ilanı metnini girin.", "error");
  const hadJobAnalysis = !el("job-results").hidden;
  resetGenerationUI(); el("generate-review").disabled = true;
  button.disabled = true; status("İş ilanı ve uyum analizi yapılıyor…");
  try {
    const response = await fetch("/api/v1/jobs/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, job_text: jobText }) });
    const data = await response.json();
    if (!response.ok) throw Error(apiMessage(data, "İş ilanı analiz edilemedi."));
    resetGenerationUI(); el("generate-review").disabled = false; renderJobSummary(data); renderJobCoach(data.job_coach.questions); el("job-results").hidden = false; status("İş ilanı analizi tamamlandı.", "success");
  } catch (error) { if (hadJobAnalysis) el("generate-review").disabled = false; status(error.message || "İş ilanı analizi sırasında bir hata oluştu.", "error"); } finally { button.disabled = false; }
};

async function recoverStoredSession() {
  const storedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!storedSessionId) return;
  try {
    const response = await fetch("/api/v1/cv/session/recover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: storedSessionId }) });
    const data = await response.json();
    if (!response.ok) throw Error(apiMessage(data, "Oturum geri yüklenemedi."));
    sessionId = data.session_id; profile(data.profile); quality(data.quality); coach("general-coach", data.coach.questions); renderCareerProfileReview(data.career_profile_review);
    el("cv-results").hidden = false; el("analyze-job").disabled = false; el("delete-session").disabled = false; enableGenerationUI();
    if (data.job_results) { renderJobSummary(data.job_results); renderJobCoach(data.job_results.job_coach.questions); el("job-results").hidden = false; }
    status("Önceki CV oturumu güvenli şekilde geri yüklendi.", "success");
  } catch (_) {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    status("Önceki oturum bulunamadı veya süresi doldu. Lütfen CV'nizi yeniden analiz edin.", "error");
  }
}

function clearDeletedSessionUI() {
  sessionId = undefined; jobTitle = ""; currentDraft = null; currentCoverLetter = null;
  el("pdf").value = ""; selectedFileNote.textContent = "";
  el("profile").innerHTML = ""; el("quality").innerHTML = ""; el("general-coach").innerHTML = "";
  el("job-text").value = ""; el("job-analysis").innerHTML = ""; el("job-score").innerHTML = ""; el("requirements").innerHTML = ""; el("job-coach").innerHTML = "";
  el("cv-results").hidden = true; el("job-results").hidden = true; el("analyze-job").disabled = true;
  el("generation-area").hidden = true; resetGenerationUI(); el("continuation-area").hidden = true; el("continuation-candidates").innerHTML = ""; el("readiness-area").hidden = true; el("readiness-items").innerHTML = "";
  el("delete-session").disabled = true;
}

el("delete-session").onclick = async () => {
  if (!sessionId || !window.confirm("Bu çalışma oturumu ve sunucuda bu oturum için saklanan veriler silinsin mi?")) return;
  const button = el("delete-session"); button.disabled = true;
  try {
    const response = await fetch("/api/v1/cv/session/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) });
    const data = await response.json(); if (!response.ok) throw Error(apiMessage(data, "Oturum silinemedi."));
    sessionStorage.removeItem(SESSION_STORAGE_KEY); clearDeletedSessionUI();
    status("Çalışma oturumu ve sunucuda bu oturum için saklanan veriler silindi.", "success");
  } catch (error) { button.disabled = false; status(error.message, "error"); }
};

recoverStoredSession();
loadPublicReleaseInfo();

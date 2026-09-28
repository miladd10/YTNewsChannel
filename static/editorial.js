
const cinemaSections=[
  ['trend','Trends'],['industry','Industry & Business'],['upcoming_films','Upcoming Films'],
  ['tv_series','TV Series'],['celebrities','Celebrities'],['ai_tech','AI & Tech'],
  ['viral_images','Viral Images'],['box_office','Box Office'],['channel_polls','Channel Polls'],
  ['now_available','Now Available in HD'],['toxic_news','Toxic News']
];
function sectionLabel(key){return cinemaSections.find(x=>x[0]===key)?.[1]||String(key||'').replaceAll('_',' ')}
const sectionGuides={
  trend:'Lead story of the week. Deepest coverage: impact, numbers, reaction, controversy and connected follow-up.',
  industry:'Studio, streaming, legal, regulatory, finance, executive and labor/business stories.',
  upcoming_films:'Trailers, first looks, casting, production starts, festival reaction, release dates and film announcements.',
  tv_series:'Renewals, cancellations, delays, premieres, showrunner changes and platform strategy tied to series.',
  celebrities:'People-focused news: honors/events, verified personal announcements, incidents and strong interview anecdotes.',
  ai_tech:'AI, VFX, production technology, virtual performers and entertainment-tech stories with a reality check.',
  viral_images:'Fast visual stories centered on a specific original post/photo/image that became notable this week.',
  box_office:'Weekly box-office rundown, totals and meaningful milestones.',
  channel_polls:'Your own channel poll results only; never invented from web research.',
  now_available:'Films newly available digitally, on VOD/PVOD, or streaming this week.',
  toxic_news:'Light, weird or embarrassing but verifiable entertainment stories for the closer.'
};
const sectionTargets={
  trend:'target 1-2',industry:'target 1-3',upcoming_films:'target 3-8',tv_series:'0-4',
  celebrities:'0-5',ai_tech:'0-3',viral_images:'0-4',box_office:'top 5 + milestone',
  channel_polls:'0-2 supplied polls',now_available:'0-4',toxic_news:'0-3'
};

researchHtml=function(){
  const counts=Object.fromEntries(cinemaSections.map(([key])=>[key,state.stories.filter(s=>s.category===key).length]));
  return `<div class="section-head"><div><div class="eyebrow">STEP 01</div><h2>Research by cinema format</h2><p>Each recurring cinema section gets its own research intent. Weak sections can stay empty instead of being padded.</p></div><button id="runResearchBtn" class="btn primary">Run Format Research</button></div>${metrics()}<div class="format-coverage">${cinemaSections.map(([key,label])=>`<div class="format-chip ${counts[key]?'has-results':''}"><strong>${counts[key]||0}</strong><span>${esc(label)}</span></div>`).join('')}</div>${state.stories.length?`<div class="run-note">AI ranking is advisory. Final section-by-section selection happens in Step 2.</div><div style="height:12px"></div>${storyCards(state.stories.slice(0,60))}`:`<div class="card placeholder">No research run yet. Run format research for ${esc(state.project.date_start)} to ${esc(state.project.date_end)}.</div>`}`;
};

pickerHtml=function(){
  const include=state.stories.filter(s=>s.decision==='include'),maybe=state.stories.filter(s=>s.decision==='maybe'),skip=state.stories.filter(s=>s.decision==='skip');
  const groups=cinemaSections.map(([key,label])=>{
    const items=state.stories.filter(s=>s.category===key);
    const inc=items.filter(s=>s.decision==='include').length;
    return `<section class="section-selection"><div class="section-selection-head"><div><div class="eyebrow">FORMAT SECTION · ${esc(sectionTargets[key]||'')}</div><h3>${esc(label)}</h3><p class="section-guide">${esc(sectionGuides[key]||'')}</p></div><span class="pill">${inc} included - ${items.length} found</span></div>${items.length?storyCards(items):`<div class="card placeholder compact-placeholder">No suitable ${esc(label)} story found in this research run.</div>`}</section>`;
  }).join('');
  return `<div class="section-head"><div><div class="eyebrow">STEP 02</div><h2>Select news inside each section</h2><p>Only <strong>Include</strong> stories are factual inputs to the narration writer, and their section assignment is preserved.</p></div></div>${metrics()}<div class="toolbar"><span class="pill">Include ${include.length}</span><span class="pill">Maybe ${maybe.length}</span><span class="pill">Skip ${skip.length}</span></div>${state.stories.length?groups:'<div class="card placeholder">Run Format Research first.</div>'}`;
};

storyCards=function(stories){
  return `<div class="story-list">${stories.map(s=>{const currentEnough=['current','followup'].includes(String(s.freshness||''));const canInclude=currentEnough&&s.temporal_gate==='pass'&&s.verification_gate==='pass'&&!!String(s.news_hook||'').trim()&&Number(s.in_window_source_count||0)>0;const freshnessLabel=s.freshness==='followup'?'Current follow-up':s.freshness==='current'?'Current':s.freshness==='stale'?'STALE / old':'Date unknown';const verificationLabel=String(s.verification_status||'needs_verification').replaceAll('_',' ');return `<article class="story-card card"><div class="story-head"><div><div class="story-title">${esc(s.canonical_title)}</div><div class="story-meta"><span class="pill">${esc(sectionLabel(s.category))}</span><span class="signal ${s.section_fit||''}">Section fit ${esc(s.section_fit||'medium')}</span><span class="signal ${currentEnough?'high':'low'}">${esc(freshnessLabel)}</span><span class="signal ${s.verification_gate==='pass'?'high':'low'}">Verification ${esc(verificationLabel)}</span><span class="signal">Current sources ${Number(s.in_window_source_count||0)}</span><span class="signal">Background ${Number(s.background_source_count||0)}</span><span class="signal ${s.attention}">Attention ${esc(s.attention)}</span><span class="signal ${s.importance}">Importance ${esc(s.importance)}</span><span class="signal">${esc(s.confidence)}</span><span class="signal">Visuals ${esc(s.visual_potential)}</span><span class="signal">${s.source_count} source${s.source_count===1?'':'s'}</span>${(s.source_platforms||[]).map(p=>`<span class="signal social-source ${esc(p)}">${esc(p==='x'?'X/Twitter':p==='tiktok'?'TikTok':p==='reddit'?'Reddit':p)}</span>`).join('')}</div></div><div class="score">${Number(s.score).toFixed(1)}</div></div>${s.news_hook?`<div class="news-hook"><div class="eyebrow">CURRENT-WINDOW NEWS HOOK${s.news_hook_date?` - ${esc(s.news_hook_date)}`:''}</div><strong>${esc(s.news_hook)}</strong></div>`:`<div class="run-note warn">No verified current-window news hook was identified. This story cannot be Included.</div>`}${s.summary?`<div class="story-summary">${esc(s.summary)}</div>`:''}<div class="story-rationale">${esc(s.rationale)}</div>${s.verification_notes?`<div class="verification-note"><strong>Verification:</strong> ${esc(s.verification_notes)}</div>`:''}${s.reddit_only?`<div class="run-note warn">Reddit-only signal: corroborate the factual claim before Include.</div>`:''}<div class="decision"><button class="btn ghost ${s.decision==='include'?'active include':''}" data-story="${s.id}" data-decision="include" ${canInclude?'':'disabled title="Needs a verified current-window news hook before Include"'}>Include</button><button class="btn ghost ${s.decision==='maybe'?'active maybe':''}" data-story="${s.id}" data-decision="maybe">Maybe</button><button class="btn ghost ${s.decision==='skip'?'active skip':''}" data-story="${s.id}" data-decision="skip">Skip</button></div><div class="source-links"><details><summary>Evidence sources (${s.articles.length})</summary>${s.articles.map(a=>`<a href="${esc(a.url)}" target="_blank" rel="noreferrer"><span class="source-kind-badge ${esc(a.platform||a.source_kind||'news')}">${esc(a.platform==='x'?'X/Twitter':a.platform==='tiktok'?'TikTok':a.platform==='reddit'?'Reddit':'News')}</span><span class="source-time-badge ${esc(a.temporal_role||'undated')}">${esc((a.temporal_role||'undated').replaceAll('_',' '))} - ${esc(a.published_at?String(a.published_at).slice(0,10):'no date')}</span> ${esc(a.source||'Source')} - ${esc(a.title)}</a>`).join('')}</details></div></article>`).join('')}</div>`;
};

runResearch=async function(){
  const b=$('#runResearchBtn');b.disabled=true;b.textContent='Researching...';
  startRunStatus({title:'Researching cinema format sections',meta:`${state.project.date_start} to ${state.project.date_end}`,steps:['Searching section queries','Clustering duplicate coverage','Ranking within format','Results saved']});
  try{
    const s=state.settings?.ai||{};
    const r=await api(`/api/projects/${state.project.id}/research`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:s.research_provider,model:s.research_model,ai_rank:true})});
    state.project=await api(`/api/projects/${state.project.id}`);
    state.stories=await api(`/api/projects/${state.project.id}/stories`);
    await renderStage();
    finishRunStatus(true,'','Format research complete');
    toast(r.ai_rank_error?`Research complete; heuristic ranking used: ${r.ai_rank_error}`:`Research complete: ${r.article_count} articles to ${r.story_count} stories`,!!r.ai_rank_error);
  }catch(e){finishRunStatus(false,e.message);toast(e.message,true);b.disabled=false;b.textContent='Run Format Research'}
};

async function loadNarrationWorkspace(){
  state.narrationWorkspace=await api(`/api/projects/${state.project.id}/narration-workspace`);
  return state.narrationWorkspace;
}
function latestReviewForDraft(workspace,draftId){return (workspace?.reviews||[]).filter(x=>x.narration_id===draftId).sort((a,b)=>Number(b.review_number)-Number(a.review_number))[0]||null}
function narrationGateBadge(review){if(!review)return '<span class="signal">Not reviewed</span>';const gate=review.gate_status||'revision_required';return `<span class="signal ${gate==='pass'?'high':gate==='polish_optional'?'medium':'low'}">${esc(gate.replaceAll('_',' '))}</span>`}

narrationHtml=async function(){
  const w=await loadNarrationWorkspace();
  const drafts=w.narrations||[];
  const enabledStyles=(w.style_transcripts||[]).filter(x=>Number(x.enabled));
  if(!state.narrationDraftId||!drafts.some(x=>x.id===state.narrationDraftId))state.narrationDraftId=drafts[0]?.id||null;
  const draft=drafts.find(x=>x.id===state.narrationDraftId)||null;
  const review=draft?latestReviewForDraft(w,draft.id):null;
  const sectionSummary=(w.sections||[]).filter(x=>x.stories?.length).map(x=>`<div class="writer-section-row"><strong>${esc(x.label)}</strong><span>${x.stories.length} selected</span><small>${esc(x.writer_role||'')}</small></div>`).join('');
  const styles=(w.style_transcripts||[]).map(t=>`<div class="style-transcript-row"><div><strong>${esc(t.name)}</strong><span>${fmt(t.char_count)} chars - ${Number(t.enabled)?'used by writer/reviewer':'disabled'}</span></div><div class="top-actions"><button class="btn ghost small-link" data-toggle-style-transcript="${t.id}" data-enabled="${Number(t.enabled)?1:0}">${Number(t.enabled)?'Disable':'Enable'}</button><button class="btn ghost small-link" data-delete-style-transcript="${t.id}">Delete</button></div></div>`).join('');
  const draftOptions=drafts.map(d=>`<option value="${d.id}" ${d.id===state.narrationDraftId?'selected':''}>Draft V${d.version_number}${Number(d.approved)?' - APPROVED':''} - ${esc(d.model)}</option>`).join('');
  return `<div class="section-head"><div><div class="eyebrow">STEP 03</div><h2>Narration Writer - Review Loop</h2><p>Selected current-week news is factual authority. Filmbaz transcripts are a separate style corpus for tone, pacing, transitions and storytelling only.</p></div><button id="generateNarrationBtn" class="btn primary">Generate Fresh Draft</button></div>${metrics()}<div class="writer-grid"><section class="card writer-panel"><div class="writer-panel-head"><div><div class="eyebrow">APPROVED NEWS INPUT</div><h3>Section plan</h3></div></div>${sectionSummary||'<div class="muted">No Included stories yet.</div>'}</section><section class="card writer-panel"><div class="writer-panel-head"><div><div class="eyebrow">STYLE CORPUS</div><h3>Filmbaz transcript library</h3><p>${enabledStyles.length} enabled transcript${enabledStyles.length===1?'':'s'} - style only, never current-week facts</p></div><button id="importStyleTranscriptsBtn" class="btn secondary">Import transcripts</button><input id="styleTranscriptFiles" type="file" accept=".txt,.md,text/plain,text/markdown" multiple class="hidden" /></div>${styles||'<div class="muted">Import Filmbaz transcript files. They are reusable across cinema weekly projects.</div>'}</section></div>${draft?`<section class="card narration-workbench"><div class="narration-toolbar"><select id="narrationDraftSelect">${draftOptions}</select><div class="top-actions">${narrationGateBadge(review)}<button id="reviewNarrationBtn" class="btn secondary">Run Reviewer</button>${review?`<button id="reviseNarrationBtn" class="btn secondary" ${review.gate_status==='pass'?'disabled':''}>Revise from Review</button>`:''}<button id="approveNarrationBtn" class="btn primary" ${Number(draft.approved)||!review||review.gate_status==='revision_required'?'disabled':''}>${Number(draft.approved)?'Approved':'Approve Draft'}</button></div></div><div class="writer-review-grid"><div><div class="eyebrow">DRAFT V${draft.version_number}</div><pre class="editor narration-editor">${esc(draft.content)}</pre></div><div><div class="eyebrow">LATEST REVIEW${review?` - R${review.review_number}`:''}</div>${review?`<div class="review-counts"><span>Blocking ${review.blocking_count}</span><span>Major ${review.major_count}</span><span>Minor ${review.minor_count}</span></div><pre class="editor review-editor">${esc(review.content)}</pre>`:'<div class="card placeholder">Run Reviewer. A passing or optional-polish review is required before approval.</div>'}</div></div></section>`:'<div class="card placeholder">Select news in Step 2, import style transcripts if available, then generate Draft V1.</div>'}`;
};

generateNarration=async function(){
  const b=$('#generateNarrationBtn');if(b){b.disabled=true;b.textContent='Writing...'}
  const s=state.settings?.ai||{};
  startRunStatus({title:'Writing fresh narration draft',meta:`${s.writer_provider||'writer'} - ${s.writer_model||'default'}`,steps:['Loading selected sections','Loading style corpus','Writer drafting','Draft saved']});
  try{
    const r=await api(`/api/projects/${state.project.id}/narration`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:s.writer_provider,model:s.writer_model})});
    state.narrationDraftId=r.id;state.project=await api(`/api/projects/${state.project.id}`);await renderStage();
    finishRunStatus(true,'',`Draft V${r.version_number} generated`);
    toast(`Draft V${r.version_number} generated - ${r.style_transcript_count} style transcript(s) used`);
  }catch(e){finishRunStatus(false,e.message);toast(e.message,true);if(b){b.disabled=false;b.textContent='Generate Fresh Draft'}}
};
async function reviewNarration(){
  const id=state.narrationDraftId;if(!id)return;const s=state.settings?.ai||{};
  startRunStatus({title:'Reviewing narration',meta:`${s.reviewer_provider||'reviewer'} - ${s.reviewer_model||'default'}`,steps:['Loading current-week sources','Comparing format and style','Building issue list','Review gate saved']});
  try{const r=await api(`/api/projects/${state.project.id}/narrations/${id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:s.reviewer_provider,model:s.reviewer_model})});await renderStage();finishRunStatus(true,'',`Review R${r.review_number}: ${r.gate_status}`);toast(`Review complete: ${r.gate_status.replaceAll('_',' ')}`)}catch(e){finishRunStatus(false,e.message);toast(e.message,true)}
}
async function reviseNarration(){
  const id=state.narrationDraftId;if(!id)return;const review=latestReviewForDraft(state.narrationWorkspace,id);if(!review)return toast('Run Reviewer first',true);const s=state.settings?.ai||{};
  startRunStatus({title:'Applying reviewer feedback',meta:'Targeted revision',steps:['Loading review change list','Applying required fixes','Preserving correct material','New draft saved']});
  try{const r=await api(`/api/projects/${state.project.id}/narrations/${id}/revise`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({review_id:review.id,provider:s.writer_provider,model:s.writer_model})});state.narrationDraftId=r.id;state.project=await api(`/api/projects/${state.project.id}`);await renderStage();finishRunStatus(true,'',`Draft V${r.version_number} revised`);toast(`Draft V${r.version_number} created from review feedback`)}catch(e){finishRunStatus(false,e.message);toast(e.message,true)}
}
async function approveNarration(){const id=state.narrationDraftId;if(!id)return;try{await api(`/api/projects/${state.project.id}/narrations/${id}/approve`,{method:'POST'});state.project=await api(`/api/projects/${state.project.id}`);await renderStage();toast('Narration approved for Voice')}catch(e){toast(e.message,true)}}
async function importStyleTranscripts(e){
  const files=[...(e.target?.files||[])];if(!files.length)return;
  startRunStatus({title:'Importing Filmbaz style transcripts',meta:`${files.length} file${files.length===1?'':'s'}`,steps:['Reading local files','Saving style corpus','Ready for writer']});
  try{for(const file of files){const content=await file.text();if(!content.trim())continue;await api('/api/style-transcripts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:file.name,content,channel:'cinema',content_type:'weekly_news',enabled:true})})}await renderStage();finishRunStatus(true,'','Style transcripts imported');toast(`${files.length} transcript file(s) imported`)}catch(err){finishRunStatus(false,err.message);toast(err.message,true)}
}
async function toggleStyleTranscript(id,enabled){try{await api(`/api/style-transcripts/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});await renderStage()}catch(e){toast(e.message,true)}}
async function deleteStyleTranscript(id){if(!confirm('Delete this style transcript from the cinema library?'))return;try{await api(`/api/style-transcripts/${id}`,{method:'DELETE'});await renderStage()}catch(e){toast(e.message,true)}}

const baseWireStageEditorial=wireStage;
wireStage=function(){
  baseWireStageEditorial();
  const nr=$('#reviewNarrationBtn');if(nr)nr.onclick=reviewNarration;
  const nv=$('#reviseNarrationBtn');if(nv)nv.onclick=reviseNarration;
  const na=$('#approveNarrationBtn');if(na)na.onclick=approveNarration;
  const ni=$('#importStyleTranscriptsBtn');if(ni)ni.onclick=()=>$('#styleTranscriptFiles')?.click();
  const nf=$('#styleTranscriptFiles');if(nf)nf.onchange=importStyleTranscripts;
  document.querySelectorAll('[data-toggle-style-transcript]').forEach(b=>b.onclick=()=>toggleStyleTranscript(b.dataset.toggleStyleTranscript,b.dataset.enabled!=='1'));
  document.querySelectorAll('[data-delete-style-transcript]').forEach(b=>b.onclick=()=>deleteStyleTranscript(b.dataset.deleteStyleTranscript));
  const nd=$('#narrationDraftSelect');if(nd)nd.onchange=()=>{state.narrationDraftId=nd.value;renderStage()};
};

const baseVoiceHtmlEditorial=voiceHtml;
voiceHtml=async function(){
  const w=await loadVoiceWorkspace();
  if(w?.narration && !Number(w.narration.approved)){
    return `<div class="section-head"><div><div class="eyebrow">STEP 04</div><h2>Narrator voice</h2><p>The Writer/Reviewer loop must approve a narration before voice generation.</p></div></div><div class="card placeholder">Return to Step 3, run Reviewer, revise if needed, then approve the narration draft.</div>`;
  }
  return baseVoiceHtmlEditorial();
};

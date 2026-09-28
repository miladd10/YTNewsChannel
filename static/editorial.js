
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
  return `<div class="section-head"><div><div class="eyebrow">STEP 02 - NEWS WINDOW ${esc(state.project.date_start)} -> ${esc(state.project.date_end)} (end exclusive)</div><h2>Select verified current news inside each section</h2><p>Include is enabled only when the story has a specific current-window news hook and source verification. Older sources may appear as background, but cannot qualify an old story as this week&#39;s news.</p></div></div>${metrics()}<div class="toolbar"><span class="pill">Include ${include.length}</span><span class="pill">Maybe ${maybe.length}</span><span class="pill">Skip ${skip.length}</span></div>${state.stories.length?groups:'<div class="card placeholder">Run Format Research first.</div>'}`;
};

storyCards=function(stories){
  return `<div class="story-list">${stories.map(s=>{const currentEnough=['current','followup'].includes(String(s.freshness||''));const canInclude=currentEnough&&s.temporal_gate==='pass'&&s.verification_gate==='pass'&&!!String(s.news_hook||'').trim()&&Number(s.in_window_source_count||0)>0;const freshnessLabel=s.freshness==='followup'?'Current follow-up':s.freshness==='current'?'Current':s.freshness==='stale'?'STALE / old':'Date unknown';const verificationLabel=String(s.verification_status||'needs_verification').replaceAll('_',' ');return `<article class="story-card card"><div class="story-head"><div><div class="story-title">${esc(s.canonical_title)}</div><div class="story-meta"><span class="pill">${esc(sectionLabel(s.category))}</span><span class="signal ${s.section_fit||''}">Section fit ${esc(s.section_fit||'medium')}</span><span class="signal ${currentEnough?'high':'low'}">${esc(freshnessLabel)}</span><span class="signal ${s.verification_gate==='pass'?'high':'low'}">Verification ${esc(verificationLabel)}</span><span class="signal">Current sources ${Number(s.in_window_source_count||0)}</span><span class="signal">Background ${Number(s.background_source_count||0)}</span><span class="signal ${s.attention}">Attention ${esc(s.attention)}</span><span class="signal ${s.importance}">Importance ${esc(s.importance)}</span><span class="signal">${esc(s.confidence)}</span><span class="signal">Visuals ${esc(s.visual_potential)}</span><span class="signal">${s.source_count} source${s.source_count===1?'':'s'}</span>${(s.source_platforms||[]).map(p=>`<span class="signal social-source ${esc(p)}">${esc(p==='x'?'X/Twitter':p==='tiktok'?'TikTok':p==='reddit'?'Reddit':p)}</span>`).join('')}</div></div><div class="score">${Number(s.score).toFixed(1)}</div></div>${s.news_hook?`<div class="news-hook"><div class="eyebrow">CURRENT-WINDOW NEWS HOOK${s.news_hook_date?` - ${esc(s.news_hook_date)}`:''}</div><strong>${esc(s.news_hook)}</strong></div>`:`<div class="run-note warn">No verified current-window news hook was identified. This story cannot be Included.</div>`}${s.summary?`<div class="story-summary">${esc(s.summary)}</div>`:''}<div class="story-rationale">${esc(s.rationale)}</div>${s.verification_notes?`<div class="verification-note"><strong>Verification:</strong> ${esc(s.verification_notes)}</div>`:''}${(s.spice_angles||[]).length?`<div class="spice-panel"><div class="eyebrow">RELATED CONTEXT / SPICE</div>${(s.spice_angles||[]).map(a=>`<div class="spice-angle ${a.safe_to_narrate?'safe':'unsafe'}"><div class="spice-angle-head"><span class="spice-type ${esc(a.type||'')}">${esc(String(a.type||'').replaceAll('_',' '))}</span><span class="spice-evidence">${esc(a.evidence_status||'weak')}${a.safe_to_narrate?' · writer may use':' · reference only'}</span></div><div class="spice-text">${esc(a.text||'')}</div>${a.usage_note?`<small>${esc(a.usage_note)}</small>`:''}</div>`).join('')}</div>`:''}${s.familiarity_needed&&s.familiarity_anchor?`<div class="familiarity-note"><strong>Casual-audience context:</strong> ${esc(s.familiarity_anchor)}</div>`:''}${s.reddit_only?`<div class="run-note warn">Reddit-only signal: corroborate the factual claim before Include.</div>`:''}<div class="decision"><button class="btn ghost ${s.decision==='include'?'active include':''}" data-story="${s.id}" data-decision="include" ${canInclude?'':'disabled title="Needs a verified current-window news hook before Include"'}>Include</button><button class="btn ghost ${s.decision==='maybe'?'active maybe':''}" data-story="${s.id}" data-decision="maybe">Maybe</button><button class="btn ghost ${s.decision==='skip'?'active skip':''}" data-story="${s.id}" data-decision="skip">Skip</button></div><div class="source-links"><details><summary>Evidence sources (${s.articles.length})</summary>${s.articles.map(a=>`<a href="${esc(a.url)}" target="_blank" rel="noreferrer"><span class="source-kind-badge ${esc(a.platform||a.source_kind||'news')}">${esc(a.platform==='x'?'X/Twitter':a.platform==='tiktok'?'TikTok':a.platform==='reddit'?'Reddit':'News')}</span><span class="source-time-badge ${esc(a.temporal_role||'undated')}">${esc((a.temporal_role||'undated').replaceAll('_',' '))} - ${esc(a.published_at?String(a.published_at).slice(0,10):'no date')}</span> ${esc(a.source||'Source')} - ${esc(a.title)}</a>`).join('')}</details></div></article>`}).join('')}</div>`;
};

runResearch=async function(){
  const b=$('#runResearchBtn');b.disabled=true;b.textContent='Researching...';
  startRunStatus({title:'Researching cinema format sections',meta:`${state.project.date_start} inclusive -> ${state.project.date_end} exclusive`,steps:['Searching current news + public social sources','Checking publication dates','Clustering duplicate coverage','Classifying section fit','Verifying current-week news hooks','Results saved']});
  try{
    const s=state.settings?.ai||{};
    const r=await api(`/api/projects/${state.project.id}/research`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:s.research_provider,model:s.research_model,ai_rank:true})});
    state.project=await api(`/api/projects/${state.project.id}`);
    state.stories=await api(`/api/projects/${state.project.id}/stories`);
    await renderStage();
    finishRunStatus(true,'','Format research complete');
    toast(r.ai_rank_error?`Research complete but semantic verification failed; stories remain gated: ${r.ai_rank_error}`:`Research complete: ${r.current_story_count} current/follow-up - ${r.verified_story_count} source-verified - ${r.stale_story_count} stale rejected`,!!r.ai_rank_error);
  }catch(e){finishRunStatus(false,e.message);toast(e.message,true);b.disabled=false;b.textContent='Run Format Research'}
};

async function loadNarrationWorkspace(){
  state.narrationWorkspace=await api(`/api/projects/${state.project.id}/narration-workspace`);
  return state.narrationWorkspace;
}
function latestReviewForDraft(workspace,draftId){return (workspace?.reviews||[]).filter(x=>x.narration_id===draftId).sort((a,b)=>Number(b.review_number)-Number(a.review_number))[0]||null}
function narrationGateBadge(review){if(!review)return '<span class="signal">Not reviewed</span>';const gate=review.gate_status||'revision_required';return `<span class="signal ${gate==='pass'?'high':gate==='polish_optional'?'medium':'low'}">${esc(gate.replaceAll('_',' '))}</span>`}


function reviewAuditBadges(review){
  if(!review)return '';
  const rows=[
    ['Format',review.format_status],
    ['Style',review.style_status],
    ['Facts',review.factual_status],
    ['Freshness',review.freshness_status],
    ['Context/Spice',review.spice_status],
    ['Storytelling',review.storytelling_status]
  ];
  return rows.map(([label,status])=>`<span class="review-audit-badge ${status==='pass'?'pass':'needs-work'}">${esc(label)}: ${esc((status||'unknown').replaceAll('_',' '))}</span>`).join('');
}
function factCheckHtml(draft){
  if(!draft)return '';
  const status=String(draft.fact_check_status||'not_run');
  let report={};
  try{report=JSON.parse(draft.fact_check_json||'{}')}catch{}
  const issues=Array.isArray(report.issues)?report.issues:[];
  const tone=status==='pass'?'pass':status==='corrected'?'corrected':'needs-work';
  const label=status==='pass'?'Passed':status==='corrected'?'Corrected automatically':'Needs human check';
  return `<section class="fact-check-panel ${tone}">
    <div class="fact-check-head"><div><div class="eyebrow">AUTOMATIC FACT CHECK</div><h3>${esc(label)}</h3></div><span class="pill">${Number(draft.fact_check_issue_count||issues.length||0)} issue${Number(draft.fact_check_issue_count||issues.length||0)===1?'':'s'}</span></div>
    <p>Checks volatile facts against fresh verification results: box-office totals/ranks, opening vs cumulative figures, release scope/dates and other time-sensitive claims.</p>
    ${issues.length?`<div class="fact-check-issues">${issues.map((x,i)=>`<div class="fact-check-issue"><strong>${i+1}. ${esc(x.claim||'Claim check')}</strong><span>${esc(x.problem||'')}</span>${x.correction_basis?`<small>Basis: ${esc(x.correction_basis)}</small>`:''}</div>`).join('')}</div>`:''}
  </section>`;
}

function claimAuditHtml(draft,workspace){
  if(!draft)return '';
  const ledger=(workspace?.claim_ledger||[]).filter(x=>x.narration_id===draft.id);
  const checks=(workspace?.claim_checks||[]).filter(x=>x.narration_id===draft.id);
  const status=String(draft.claim_audit_status||'not_run');
  const pass=status==='pass'&&Number(draft.claim_blocked_count||0)===0;
  const blocked=checks.filter(x=>x.status==='blocked');
  const verified=checks.filter(x=>x.status==='verified');
  const attributed=checks.filter(x=>x.status==='verified_with_attribution');
  const blockedLedger=ledger.filter(x=>x.verification_status==='blocked');
  const ledgerVerified=ledger.filter(x=>x.verification_status==='verified');
  const ledgerAttributed=ledger.filter(x=>x.verification_status==='verified_with_attribution');
  const tone=pass?'pass':'needs-work';
  const rows=[...blocked,...attributed,...verified];
  return `<section class="claim-audit-panel ${tone}">
    <div class="claim-audit-head">
      <div><div class="eyebrow">ATOMIC CLAIM LEDGER</div><h3>${pass?'All narration claims verified':status==='not_run'?'Claim audit not run':'Claim audit blocked'}</h3></div>
      <button id="runClaimAuditBtn" class="btn secondary">${status==='not_run'?'Run Claim Audit':'Re-run Claim Audit'}</button>
    </div>
    <p>Every checkable statement is mapped to source-backed atomic claims. Numbers, rankings, budgets, revenue, deal values, dates, release scope and title identity must preserve the ledger's exact meaning.</p>
    <div class="claim-audit-metrics">
      <span class="signal ${pass?'high':'low'}">Narration ${Number(draft.claim_count||checks.length)} claims</span>
      <span class="signal high">${Number(draft.claim_verified_count||verified.length)} verified</span>
      <span class="signal medium">${Number(draft.claim_attributed_count||attributed.length)} attributed</span>
      <span class="signal ${Number(draft.claim_blocked_count||blocked.length)?'low':'high'}">${Number(draft.claim_blocked_count||blocked.length)} blocked</span>
      <span class="signal">Ledger ${ledger.length}: ${ledgerVerified.length} verified · ${ledgerAttributed.length} attributed · ${blockedLedger.length} blocked</span>
    </div>
    ${blocked.length?`<div class="claim-blocked-list">${blocked.map(x=>`<div class="claim-check-row blocked"><div><span class="pill">${esc(String(x.claim_type||'claim').replaceAll('_',' '))}</span><strong>${esc(x.sentence||'')}</strong></div><small>${esc(x.issue||'Unsupported or scope-mismatched claim.')}</small></div>`).join('')}</div>`:''}
    ${rows.length?`<details class="claim-audit-details"><summary>Show narration claim mapping (${rows.length})</summary><div class="claim-check-list">${rows.map(x=>`<div class="claim-check-row ${esc(x.status||'blocked')}"><div><span class="claim-status">${esc(String(x.status||'blocked').replaceAll('_',' '))}</span><span class="pill">${esc(String(x.claim_type||'claim').replaceAll('_',' '))}</span><strong>${esc(x.sentence||'')}</strong></div><small>${(x.ledger_claim_ids||[]).length?`Ledger: ${esc((x.ledger_claim_ids||[]).join(', '))}`:'No ledger mapping'}${x.issue?` · ${esc(x.issue)}`:''}</small></div>`).join('')}</div></details>`:''}
    ${ledger.length?`<details class="claim-audit-details"><summary>Show verified source ledger (${ledger.length})</summary><div class="claim-ledger-list">${ledger.map(x=>`<div class="claim-ledger-row ${esc(x.verification_status||'blocked')}"><div><span class="claim-id">${esc(x.id||'')}</span><span class="pill">${esc(String(x.claim_type||'claim').replaceAll('_',' '))}</span><strong>${esc(x.canonical_text||'')}</strong></div><small>${[x.metric,x.market,x.chart_type,x.period_type,x.date_start&&x.date_end?`${x.date_start} → ${x.date_end}`:'',x.attribution_required?'attribution required':''].filter(Boolean).map(esc).join(' · ')}</small>${(x.source_urls||[]).length?`<div class="claim-source-links">${(x.source_urls||[]).map((url,i)=>`<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc((x.source_names||[])[i]||'Source')}</a>`).join('')}</div>`:''}</div>`).join('')}</div></details>`:''}
  </section>`;
}

function reviewFeedbackHtml(review){
  if(!review){
    return `<section id="reviewFeedbackPanel" class="review-feedback-panel empty"><div><div class="eyebrow">REVIEW FEEDBACK</div><h3>No review yet</h3><p>Run Reviewer to get a visible format, style, factual, freshness, context/spice and storytelling audit for this exact draft.</p></div></section>`;
  }
  return `<section id="reviewFeedbackPanel" class="review-feedback-panel"><div class="review-feedback-head"><div><div class="eyebrow">REVIEW FEEDBACK · R${Number(review.review_number||1)}</div><h3>${esc(String(review.gate_status||'revision_required').replaceAll('_',' '))}</h3></div><div class="review-counts"><span>Blocking ${Number(review.blocking_count||0)}</span><span>Major ${Number(review.major_count||0)}</span><span>Minor ${Number(review.minor_count||0)}</span></div></div><div class="review-audits">${reviewAuditBadges(review)}</div><pre class="editor review-editor review-feedback-text">${esc(review.content||'')}</pre></section>`;
}


function storyEnrichmentHtml(stories,draft){
  if(!draft)return '';
  const draftTime=Date.parse(draft.created_at||'')||0;
  const searched=stories.filter(s=>s.context_searched_at);
  const pending=stories.filter(s=>(Date.parse(s.context_searched_at||'')||0)>draftTime);
  const safeCount=stories.reduce((n,s)=>n+(s.spice_angles||[]).filter(a=>a.safe_to_narrate).length,0);
  const funFactCount=stories.reduce((n,s)=>n+(s.spice_angles||[]).filter(a=>a.safe_to_narrate&&a.type==='cool_fact').length,0);
  const visualContextCount=stories.reduce((n,s)=>n+(s.visual_context||[]).length,0);
  return `<section class="card enrichment-workbench">
    <div class="enrichment-head">
      <div>
        <div class="eyebrow">POST-DRAFT FUN FACTS + VISUAL CONTEXT</div>
        <h3>Enrich the narration and build professional B-roll targets</h3>
        <p>One click searches every Included story for sourced cool facts and visual context, then rewrites the draft. It also maps people, related movies/shows, interviews, BTS, event photos and comparisons so Media Sources is driven by what the narration actually says.</p>
      </div>
      <div class="top-actions">
        <span class="pill">${searched.length}/${stories.length} searched</span>
        <span class="pill">${funFactCount} fun fact${funFactCount===1?'':'s'}</span>
        <span class="pill">${visualContextCount} visual beat${visualContextCount===1?'':'s'}</span>
        <button id="buildFunFactsVisualsBtn" class="btn primary">Add Fun Facts + Visual Context</button>
        <button id="rewriteEnrichedBtn" class="btn secondary" ${pending.length?'':'disabled'}>Rewrite Existing Enrichment${pending.length?` (${pending.length} updated)`:''}</button>
      </div>
    </div>
    ${pending.length?`<div class="run-note warn">New story research was added after Draft V${draft.version_number}. Rewrite with Enrichment before running Reviewer so the review evaluates the enriched draft.</div>`:''}
    <div class="enrichment-story-list">${stories.map(s=>{
      const angles=s.spice_angles||[];
      const sources=s.spice_sources||[];
      const safe=angles.filter(a=>a.safe_to_narrate);
      const visuals=s.visual_context||[];
      const searchedAt=s.context_searched_at||'';
      return `<article class="enrichment-story">
        <div class="enrichment-story-head">
          <div>
            <strong>${esc(s.canonical_title)}</strong>
            <div class="story-meta">
              <span class="pill">${esc(sectionLabel(s.category))}</span>
              ${searchedAt?`<span class="signal high">searched ${Number(s.context_search_count||1)}x</span>`:'<span class="signal">not searched yet</span>'}
              <span class="signal">${safe.length} usable angle${safe.length===1?'':'s'}</span>
              <span class="signal">${visuals.length} visual target${visuals.length===1?'':'s'}</span>
              <span class="signal">${sources.length} collected source${sources.length===1?'':'s'}</span>
            </div>
          </div>
          <button class="btn secondary" data-search-story-context="${s.id}">${searchedAt?'Search Again':'Find Cool Stuff'}</button>
        </div>
        ${angles.length?`<div class="enrichment-angle-list">${angles.map(a=>`<div class="spice-angle ${a.safe_to_narrate?'safe':'unsafe'}"><div class="spice-angle-head"><span class="spice-type ${esc(a.type||'')}">${esc(String(a.type||'').replaceAll('_',' '))}</span><span class="spice-evidence">${esc(a.evidence_status||'weak')}${a.safe_to_narrate?' - usable':' - reference only'}</span></div><div class="spice-text">${esc(a.text||'')}</div>${a.usage_note?`<small>${esc(a.usage_note)}</small>`:''}</div>`).join('')}</div>`:''}
        ${visuals.length?`<div class="visual-context-list"><div class="eyebrow">NARRATION-AWARE VISUAL TARGETS</div>${visuals.map(v=>`<div class="visual-context-item"><div><span class="pill">${esc(String(v.kind||'visual').replaceAll('_',' '))}</span><strong>${esc(v.label||(v.subjects||[]).join(' + '))}</strong><span class="signal">${esc(v.layout_hint||'single')}</span></div>${v.narration_cue?`<small>When narration says: ${esc(v.narration_cue)}</small>`:''}${v.why?`<p>${esc(v.why)}</p>`:''}</div>`).join('')}</div>`:''}
        ${sources.length?`<details class="enrichment-sources"><summary>Collected sources (${sources.length}) - also passed to Media Sources</summary>${sources.map(src=>`<a href="${esc(src.url)}" target="_blank" rel="noreferrer"><span class="source-kind-badge ${esc(src.platform||src.source_kind||'web')}">${esc(src.platform==='x'?'X/Twitter':src.platform==='reddit'?'Reddit':src.platform==='tiktok'?'TikTok':src.platform==='instagram'?'Instagram':src.platform==='youtube'?'YouTube':'Web')}</span> ${esc(src.source||'Source')} - ${esc(src.title||src.url)}</a>`).join('')}</details>`:''}
        ${s.context_search_error?`<div class="run-note warn">${esc(s.context_search_error)}</div>`:''}
      </article>`;
    }).join('')}</div>
  </section>`;
}

narrationHtml=async function(){
  const w=await loadNarrationWorkspace();
  const drafts=w.narrations||[];
  const enabledStyles=(w.style_transcripts||[]).filter(x=>Number(x.enabled));
  if(!state.narrationDraftId||!drafts.some(x=>x.id===state.narrationDraftId))state.narrationDraftId=drafts[0]?.id||null;
  const draft=drafts.find(x=>x.id===state.narrationDraftId)||null;
  const savedReview=draft?latestReviewForDraft(w,draft.id):null;
  const instantReview=(draft&&state.lastNarrationReview&&state.lastNarrationReview.narration_id===draft.id)?state.lastNarrationReview:null;
  const review=instantReview||savedReview;
  const sectionSummary=(w.sections||[]).filter(x=>x.stories?.length).map(x=>`<div class="writer-section-row"><strong>${esc(x.label)}</strong><span>${x.stories.length} selected</span><small>${esc(x.writer_role||'')}</small></div>`).join('');
  const familiarityCount=(w.sections||[]).flatMap(x=>x.stories||[]).filter(x=>x.familiarity_needed&&x.familiarity_anchor).length;
  const styles=(w.style_transcripts||[]).map(t=>`<div class="style-transcript-row"><div><strong>${esc(t.name)}</strong><span>${fmt(t.char_count)} chars - ${Number(t.enabled)?'used by writer/reviewer':'disabled'}</span></div><div class="top-actions"><button class="btn ghost small-link" data-toggle-style-transcript="${t.id}" data-enabled="${Number(t.enabled)?1:0}">${Number(t.enabled)?'Disable':'Enable'}</button><button class="btn ghost small-link" data-delete-style-transcript="${t.id}">Delete</button></div></div>`).join('');
  const styleProfile=w.style_profile||{};
  const styleProfileHtml=`<div class="style-profile-card ${styleProfile.current?'current':styleProfile.stale?'stale':'missing'}"><div class="style-profile-head"><div><strong>Style Blueprint</strong><span>${styleProfile.current?'Current':styleProfile.stale?'Stale - references changed':'Not built yet'} · ${Number(styleProfile.enabled_transcript_count||0)} enabled transcript${Number(styleProfile.enabled_transcript_count||0)===1?'':'s'}</span></div><button id="rebuildStyleProfileBtn" class="btn secondary small-link">${styleProfile.current?'Rebuild Blueprint':'Build Blueprint'}</button></div>${styleProfile.profile_text?`<details><summary>What the app learned from the references</summary><pre class="editor style-profile-text">${esc(styleProfile.profile_text)}</pre></details>`:''}</div>`;
  const draftOptions=drafts.map(d=>`<option value="${d.id}" ${d.id===state.narrationDraftId?'selected':''}>Draft V${d.version_number}${Number(d.approved)?' - APPROVED':''} - ${esc(d.model)}</option>`).join('');
  const selectedStories=(w.sections||[]).flatMap(x=>x.stories||[]);
  const draftTime=draft?(Date.parse(draft.created_at||'')||0):0;
  const pendingEnrichment=draft?selectedStories.some(s=>(Date.parse(s.context_searched_at||'')||0)>draftTime):false;
  const factStatus=String(draft?.fact_check_status||'not_run');
  const factReady=['pass','corrected'].includes(factStatus);
  const claimStatus=String(draft?.claim_audit_status||'not_run');
  const claimReady=claimStatus==='pass'&&Number(draft?.claim_blocked_count||0)===0&&Number(draft?.claim_count||0)>0;
  return `<div class="section-head"><div><div class="eyebrow">STEP 03</div><h2>Narration Writer - Review Loop</h2><p>Selected current-week news is factual authority. The full Filmbaz library teaches recurring tone, pacing, compact context and storytelling behavior. Non-obvious people/companies can use one short verified familiarity cue.</p></div><button id="generateNarrationBtn" class="btn primary">Generate Baseline Draft</button></div>${metrics()}<div class="writer-grid"><section class="card writer-panel"><div class="writer-panel-head"><div><div class="eyebrow">APPROVED NEWS INPUT</div><h3>Section plan</h3><p>${familiarityCount} selected story/stories include a casual-audience familiarity anchor.</p></div></div>${sectionSummary||'<div class="muted">No Included stories yet.</div>'}</section><section class="card writer-panel"><div class="writer-panel-head"><div><div class="eyebrow">STYLE CORPUS</div><h3>Filmbaz transcript library</h3><p>${enabledStyles.length} enabled transcript${enabledStyles.length===1?'':'s'} - the app now distills them into a reusable Style Blueprint and also preserves long flow anchors from complete episodes.</p></div><button id="importStyleTranscriptsBtn" class="btn secondary">Import transcripts</button><input id="styleTranscriptFiles" type="file" accept=".txt,.md,text/plain,text/markdown" multiple class="hidden" /></div>${styleProfileHtml}${styles||'<div class="muted">Import Filmbaz transcript files. They are reusable across cinema weekly projects.</div>'}</section></div>${storyEnrichmentHtml(selectedStories,draft)}${draft?`<section class="card narration-workbench"><div class="narration-toolbar"><select id="narrationDraftSelect">${draftOptions}</select><div class="top-actions">${narrationGateBadge(review)}<button id="reviewNarrationBtn" class="btn secondary" ${pendingEnrichment?'disabled title="Rewrite with Enrichment first"':''}>Run Reviewer</button>${review?`<button id="reviseNarrationBtn" class="btn secondary" ${review.gate_status==='pass'?'disabled':''}>Revise from Review</button>`:''}<button id="approveNarrationBtn" class="btn primary" ${Number(draft.approved)||!review||review.gate_status==='revision_required'||!factReady||!claimReady?'disabled':''} ${!factReady?'title="Automatic fact check must pass before approval"':!claimReady?'title="Atomic Claim Ledger audit must pass before approval"':''}>${Number(draft.approved)?'Approved':'Approve Draft'}</button></div></div>${factCheckHtml(draft)}${claimAuditHtml(draft,w)}${reviewFeedbackHtml(review)}<div class="draft-feedback-panel"><div class="eyebrow">DRAFT V${draft.version_number}</div><pre class="editor narration-editor">${esc(draft.content)}</pre></div></section>`:'<div class="card placeholder">Select news in Step 2, import style transcripts if available, then generate Draft V1.</div>'}`;
};


generateNarration=async function(){
  const b=$('#generateNarrationBtn');if(b){b.disabled=true;b.textContent='Writing...'}
  const s=state.settings?.ai||{};
  startRunStatus({title:'Writing + validating baseline narration',meta:`${s.writer_provider||'writer'} - ${s.writer_model||'default'}`,steps:['Loading selected sections','Building verified atomic Claim Ledger','Planning only ledger-backed facts','Writing spoken draft','Fresh-search fact check','Extracting every narration claim','Comparing claims to ledger','Draft saved']});
  try{
    const r=await api(`/api/projects/${state.project.id}/narration`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:s.writer_provider,model:s.writer_model})});
    state.narrationDraftId=r.id;state.lastNarrationReview=null;state.project=await api(`/api/projects/${state.project.id}`);await renderStage();
    finishRunStatus(true,'',`Draft V${r.version_number} generated`);
    toast(r.content_plan_error?`Draft V${r.version_number} generated, but the fact-plan pass fell back: ${r.content_plan_error}`:`Draft V${r.version_number} · fact check ${String(r.fact_check_status||'unknown').replaceAll('_',' ')} · claims ${r.claim_verified_count||0} verified / ${r.claim_attributed_count||0} attributed / ${r.claim_blocked_count||0} blocked`,!!r.content_plan_error||r.fact_check_status==='needs_human_check'||r.claim_audit_status!=='pass');
  }catch(e){finishRunStatus(false,e.message);toast(e.message,true);if(b){b.disabled=false;b.textContent='Generate Fresh Draft'}}
};
async function rebuildStyleProfile(){
  const b=$('#rebuildStyleProfileBtn');if(b){b.disabled=true;b.textContent='Analyzing...'}
  const s=state.settings?.ai||{};
  startRunStatus({title:'Building narration style blueprint',meta:'Analyzing all enabled Filmbaz references',steps:['Loading full reference library','Comparing recurring oral patterns','Studying long flow anchors','Distilling story micro-arcs + transitions','Saving style blueprint']});
  try{
    const r=await api(`/api/projects/${state.project.id}/style-profile/rebuild`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:s.writer_provider,model:s.writer_model})
    });
    await renderStage();
    finishRunStatus(true,'',`Style Blueprint rebuilt from ${r.transcript_count} transcript(s)`);
    toast(`Style Blueprint rebuilt from ${r.transcript_count} transcript(s)`);
    setTimeout(()=>document.querySelector('.style-profile-card')?.scrollIntoView({behavior:'smooth',block:'center'}),60);
  }catch(e){
    finishRunStatus(false,e.message);toast(e.message,true);
    if(b){b.disabled=false;b.textContent='Build Blueprint'}
  }
}

async function searchStoryContext(storyId){
  const b=document.querySelector(`[data-search-story-context="${storyId}"]`);
  if(b){b.disabled=true;b.textContent='Searching...'}
  const s=state.settings?.ai||{};
  startRunStatus({title:'Searching related context for one story',meta:'Public web + Reddit + X/Twitter + TikTok + Instagram + YouTube',steps:['Searching general web','Searching rumors / controversy','Searching critic reaction','Searching Reddit + X + TikTok + Instagram','Searching interviews / behind the scenes','Validating sources and safe angles','Saving sources for Narration + Media']});
  try{
    const r=await api(`/api/projects/${state.project.id}/stories/${storyId}/context-search`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:s.research_provider,model:s.research_model})
    });
    state.lastNarrationReview=null;
    await renderStage();
    finishRunStatus(true,'',`Story enrichment complete: ${r.safe_angle_count} usable angle(s), ${r.source_count} collected source(s)`);
    toast(`Found ${r.safe_angle_count} usable angle(s) from ${r.source_count} collected source(s)`);
    setTimeout(()=>document.querySelector(`[data-search-story-context="${storyId}"]`)?.scrollIntoView({behavior:'smooth',block:'center'}),60);
  }catch(e){
    finishRunStatus(false,e.message);
    toast(e.message,true);
    if(b){b.disabled=false;b.textContent='Find Cool Stuff'}
  }
}
async function buildFunFactsVisualContext(){
  const id=state.narrationDraftId;if(!id)return;
  const b=$('#buildFunFactsVisualsBtn');if(b){b.disabled=true;b.textContent='Researching + rewriting...'}
  const s=state.settings?.ai||{};
  startRunStatus({title:'Adding fun facts + narration-aware visual context',meta:'All Included stories · one post-draft action',steps:['Reading the actual draft','Searching sourced cool facts + production context','Mapping people / related titles / interviews / BTS','Building Media visual targets','Rewriting the draft with clean fun-fact beats','Saving enriched draft']});
  try{
    const research=await api(`/api/projects/${state.project.id}/narrations/${id}/fun-facts-visual-context`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:s.research_provider,model:s.research_model})
    });
    const rewritten=await api(`/api/projects/${state.project.id}/narrations/${id}/enrich-rewrite`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:s.writer_provider,model:s.writer_model})
    });
    state.narrationDraftId=rewritten.id;
    state.lastNarrationReview=null;
    state.project=await api(`/api/projects/${state.project.id}`);
    await renderStage();
    finishRunStatus(true,'',`Draft V${rewritten.version_number} enriched · ${research.fun_fact_count} fun fact(s) · ${research.visual_context_count} visual target(s)`);
    toast(`Added ${research.fun_fact_count} sourced fun fact(s) and ${research.visual_context_count} narration-aware visual target(s). Draft V${rewritten.version_number} is ready for review.`);
  }catch(e){
    finishRunStatus(false,e.message);toast(e.message,true);
    if(b){b.disabled=false;b.textContent='Add Fun Facts + Visual Context'}
  }
}

async function rewriteWithEnrichment(){
  const id=state.narrationDraftId;if(!id)return;
  const b=$('#rewriteEnrichedBtn');if(b){b.disabled=true;b.textContent='Rewriting...'}
  const s=state.settings?.ai||{};
  startRunStatus({title:'Rewriting + fact-checking enriched draft',meta:`${s.writer_provider||'writer'} - ${s.writer_model||'default'}`,steps:['Loading per-story searches','Using only safe evidence-backed angles','Preserving good draft structure','Fresh-search fact check','Saving enriched draft']});
  try{
    const r=await api(`/api/projects/${state.project.id}/narrations/${id}/enrich-rewrite`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:s.writer_provider,model:s.writer_model})
    });
    state.narrationDraftId=r.id;
    state.lastNarrationReview=null;
    state.project=await api(`/api/projects/${state.project.id}`);
    await renderStage();
    finishRunStatus(true,'',`Draft V${r.version_number} enriched with ${r.safe_angle_count} safe angle(s)`);
    toast(`Enriched Draft V${r.version_number} created. Run Reviewer next.`);
  }catch(e){
    finishRunStatus(false,e.message);toast(e.message,true);
    if(b){b.disabled=false;b.textContent='Rewrite with Enrichment'}
  }
}

async function reviewNarration(){
  const id=state.narrationDraftId;if(!id)return;const s=state.settings?.ai||{};const b=$('#reviewNarrationBtn');
  if(b){b.disabled=true;b.textContent='Reviewing...'}
  startRunStatus({title:'Reviewing narration',meta:`${s.reviewer_provider||'reviewer'} - ${s.reviewer_model||'default'}`,steps:['Loading current-week + enrichment sources','Checking rumor/social/critic attribution','Comparing full reference style corpus','Checking familiarity context + naturalness','Building issue list','Review gate saved']});
  try{
    const r=await api(`/api/projects/${state.project.id}/narrations/${id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:s.reviewer_provider,model:s.reviewer_model})});
    state.lastNarrationReview={...r,narration_id:r.narration_id||id};
    if(state.narrationWorkspace){
      state.narrationWorkspace.reviews=(state.narrationWorkspace.reviews||[]).filter(x=>x.id!==r.id);
      state.narrationWorkspace.reviews.unshift(state.lastNarrationReview);
    }
    await renderStage();
    finishRunStatus(true,'',`Review R${r.review_number}: ${r.gate_status}`);
    toast(`Review complete: ${r.gate_status.replaceAll('_',' ')}`);
    setTimeout(()=>document.querySelector('#reviewFeedbackPanel')?.scrollIntoView({behavior:'smooth',block:'start'}),60);
  }catch(e){finishRunStatus(false,e.message);toast(e.message,true);if(b){b.disabled=false;b.textContent='Run Reviewer'}}
}
async function reviseNarration(){
  const id=state.narrationDraftId;if(!id)return;const review=latestReviewForDraft(state.narrationWorkspace,id);if(!review)return toast('Run Reviewer first',true);const s=state.settings?.ai||{};
  startRunStatus({title:'Applying review + rechecking facts',meta:'Targeted revision',steps:['Loading review change list','Applying required fixes','Preserving correct material','Fresh-search fact check','New draft saved']});
  try{const r=await api(`/api/projects/${state.project.id}/narrations/${id}/revise`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({review_id:review.id,provider:s.writer_provider,model:s.writer_model})});state.narrationDraftId=r.id;state.lastNarrationReview=null;state.project=await api(`/api/projects/${state.project.id}`);await renderStage();finishRunStatus(true,'',`Draft V${r.version_number} revised`);toast(`Draft V${r.version_number} created from review feedback`)}catch(e){finishRunStatus(false,e.message);toast(e.message,true)}
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
  const sp=$('#rebuildStyleProfileBtn');if(sp)sp.onclick=rebuildStyleProfile;
  const fv=$('#buildFunFactsVisualsBtn');if(fv)fv.onclick=buildFunFactsVisualContext;
  const re=$('#rewriteEnrichedBtn');if(re)re.onclick=rewriteWithEnrichment;
  document.querySelectorAll('[data-search-story-context]').forEach(b=>b.onclick=()=>searchStoryContext(b.dataset.searchStoryContext));
  const nv=$('#reviseNarrationBtn');if(nv)nv.onclick=reviseNarration;
  const na=$('#approveNarrationBtn');if(na)na.onclick=approveNarration;
  const ni=$('#importStyleTranscriptsBtn');if(ni)ni.onclick=()=>$('#styleTranscriptFiles')?.click();
  const nf=$('#styleTranscriptFiles');if(nf)nf.onchange=importStyleTranscripts;
  document.querySelectorAll('[data-toggle-style-transcript]').forEach(b=>b.onclick=()=>toggleStyleTranscript(b.dataset.toggleStyleTranscript,b.dataset.enabled!=='1'));
  document.querySelectorAll('[data-delete-style-transcript]').forEach(b=>b.onclick=()=>deleteStyleTranscript(b.dataset.deleteStyleTranscript));
  const nd=$('#narrationDraftSelect');if(nd)nd.onchange=()=>{state.narrationDraftId=nd.value;state.lastNarrationReview=null;renderStage()};
};

const baseVoiceHtmlEditorial=voiceHtml;
voiceHtml=async function(){
  const w=await loadVoiceWorkspace();
  if(w?.narration && !Number(w.narration.approved)){
    return `<div class="section-head"><div><div class="eyebrow">STEP 04</div><h2>Narrator voice</h2><p>The Writer/Reviewer loop must approve a narration before voice generation.</p></div></div><div class="card placeholder">Return to Step 3, run Reviewer, revise if needed, then approve the narration draft.</div>`;
  }
  return baseVoiceHtmlEditorial();
};

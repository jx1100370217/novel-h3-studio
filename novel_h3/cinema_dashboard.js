/* Read-only projection of the versioned chapter production workflow. */
const cinemaLabels={pending:'待拍摄',generating:'拍摄中',screening:'声音核对中',saved:'候选已保存',checked:'声音检查通过',needs_rework:'需重拍',failed:'拍摄失败'};
const cinemaTime=t=>t?new Date(t*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
function cinemaLink(label,path){const a=el('a',label);a.href='/media?path='+encodeURIComponent(path);a.target='_blank';a.rel='noopener';return a}
function cinemaConnection(panel,error){const note=panel.querySelector('[data-slot="freshness"]');if(note){note.textContent='连接中断 · 保留最近一次数据 · '+error.message;note.className='error'}else panel.textContent='连接中断：'+error.message;const status=$('connectionLabel');if(status)status.textContent='连接中断'}
function cinemaShell(panel,mode){
 panel.replaceChildren();
 panel.classList.add('cinema-dashboard');panel.dataset.mode=mode;
 const head=el('section',undefined,'dashboard-hero');head.append(el('div','CHAPTER PRODUCTION · V2','eyebrow'));
 for(const slot of ['title','phase','freshness']){const node=el(slot==='title'?'h3':'p',undefined,slot==='freshness'?'muted':'');node.dataset.slot=slot;head.append(node)}
 const kpis=el('div',undefined,'cinema-kpis');kpis.dataset.slot='kpis';
 const stages=el('div',undefined,'cinema-stages');stages.dataset.slot='stages';
 const activity=card('当前执行');activity.dataset.slot='activity';
 const sources=card('制作资料');sources.dataset.slot='sources';
 const review=card('全章审片版');review.dataset.slot='review';
 const shots=card('全章镜头台账');shots.dataset.slot='shots';
 const tools=el('div',undefined,'row cinema-filters');const search=el('input');search.placeholder='搜索镜号、场景或剧情';search.setAttribute('aria-label','搜索新版镜头');
 const filter=el('select');filter.setAttribute('aria-label','筛选新版镜头状态');
 for(const [value,label] of [['all','全部镜头'],['checked','声音检查通过'],['needs_rework','需重拍'],['active','正在执行'],['pending','尚未保存']]){const o=el('option',label);o.value=value;filter.append(o)}
 const count=el('span',undefined,'muted');count.dataset.slot='rowcount';tools.append(search,filter,count);
 const box=el('div',undefined,'tablebox cinema-table');const table=el('table');const thead=el('thead'),tr=el('tr');for(const label of ['镜号 / 剧情','场景 / 台词','制作状态','当前候选'])tr.append(el('th',label));thead.append(tr);const tbody=el('tbody');table.append(thead,tbody);box.append(table);shots.append(tools,box);
 const showRows=()=>cinemaRows(panel,panel.cinemaData);search.oninput=showRows;filter.onchange=showRows;
 panel.append(head,kpis,stages,activity,review,sources,shots);
}
function cinemaRows(panel,p){
 if(!p)return;const search=panel.querySelector('input'),filter=panel.querySelector('select'),body=panel.querySelector('tbody');
 const needle=search.value.trim().toLowerCase(),choice=filter.value;
 const rows=p.shots.filter(r=>(r.shot+' '+r.title+' '+r.scene+' '+r.dialogue).toLowerCase().includes(needle)&&(choice==='all'||choice==='active'&&r.active||choice==='pending'&&!r.saved||r.status===choice));
 body.replaceChildren();panel.querySelector('[data-slot="rowcount"]').textContent=rows.length+' / '+p.counts.planned+' 镜';
 for(const r of rows){const tr=el('tr');tr.dataset.shot=r.shot;const title=el('td');title.append(el('b',r.shot),el('div',r.title));const scene=el('td');scene.append(el('div',r.scene||'—'),el('small',r.dialogue||'无对白 · 环境声 / 动作声','muted'));
 const status=el('td');status.append(el('span',cinemaLabels[r.status]||r.status,'cinema-badge '+r.status),el('small','候选 '+r.attempts+' 版 · '+(r.human_approved?'已人工审核':'影视质量待审核'),'muted'));
 if(r.active&&r.saved)status.append(el('small','链接为上一版已保存候选','muted'));if(r.error)status.append(el('small',r.error,'error'));
 const links=el('td',undefined,'cinema-links');if(r.video)links.append(cinemaLink('播放音画',r.video));if(r.contact)links.append(cinemaLink('画面抽检',r.contact));if(r.report)links.append(cinemaLink('声音报告',r.report));if(!r.video)links.append(el('span','尚无可播放候选','muted'));tr.append(title,scene,status,links);body.append(tr)}
}
function renderCinemaDashboard(panel,p,mode='progress'){
 if(!panel.querySelector('[data-slot="freshness"]'))cinemaShell(panel,mode);
 panel.cinemaData=p;panel.dataset.observedAt=p.observed_at;
 const slot=name=>panel.querySelector('[data-slot="'+name+'"]');const c=p.counts;
 slot('title').textContent=displayTitle(p.title);slot('phase').textContent=p.phase_label;
 slot('freshness').className='muted';slot('freshness').textContent='实时连接 · 每 3 秒刷新 · 读取 '+cinemaTime(p.observed_at)+' · 制作记录 '+cinemaTime(p.updated_at);
 const connection=$('connectionLabel');if(connection)connection.textContent='工作台已连接';
 slot('kpis').replaceChildren();
 for(const [label,value,note] of [['镜头候选已保存',c.saved+' / '+c.planned,'全章计划，按镜头去重'],['声音自动检查',c.sound_passed+' / '+c.planned,'台词 / 无对白检查'],['待重拍 / 待声音检查',c.needs_rework+' / '+c.sound_pending,'检查失败与未检查分别统计'],['白话对白准备',p.audio_passed+' / '+p.audio_total,'已通过目标音频核对'],['镜头人工审核',c.human_approved+' / '+c.planned,'剧情、表演与真实音画同步'],['全章审片版',p.review.ready?'可播放':['failed','interrupted'].includes(p.status)?'导出已停止':'尚未导出',p.review.approved?'已人工验收':'尚未人工验收']]){const box=card(label);box.append(el('div',value,'stat'),el('p',note,'muted'));slot('kpis').append(box)}
 slot('stages').replaceChildren();p.stages.forEach((s,i)=>{const box=el('section',undefined,'cinema-stage '+s.status);box.append(el('span',String(i+1).padStart(2,'0'),'eyebrow'),el('h3',s.title),el('p',s.current+' / '+s.total+' · '+({done:'已完成',active:'当前节点',pending:'待开始',failed:'已停止'}[s.status]),'cinema-stage-state'));const bar=el('progress');bar.max=s.total||1;bar.value=s.current;box.append(bar,el('p',s.detail,'muted'));slot('stages').append(box)});
 const activity=slot('activity');activity.replaceChildren(el('h3','当前执行'));
 activity.append(el('p',p.stage||p.phase_label,'cinema-current'));if(p.shot&&['generating','speech_screening'].includes(p.status))activity.append(el('p','正在处理 '+p.shot+(p.steps!=null?' · 采样 '+p.steps+' / '+p.steps_total+' 步':' · '+p.phase_label)));
 if(p.active_batch.is_repair)activity.append(el('p','重拍批次 '+p.active_batch.completed+' / '+p.active_batch.total+' 镜 · 全章仍为 '+c.planned+' 镜','warn'));
 if(p.worker_alive!==null&&p.worker_alive!==undefined)activity.append(el('p',p.worker_alive?'制作进程正在运行 · PID '+p.worker_pid:p.review.ready?'制作任务已完成 · 等待人工审片':'制作进程已停止','muted'));
 if(p.phase==='editing'&&p.edit_progress.stage){const e=p.edit_progress;activity.append(el('p',({rendering_segments:'镜头中间文件合成',encoding_chapter:'全章编码与文字合成',completed:'视频已导出，正在更新制作记录'}[e.stage]||e.stage)+' · '+e.completed+' / '+e.total+' 镜','cinema-current'))}
 if(p.note)activity.append(el('p',p.note,'muted'));if(['failed','interrupted'].includes(p.status)&&p.error)activity.append(el('p',p.error,'error'));
 if(p.resources){const r=p.resources,fmt=n=>Number.isFinite(n)?n.toFixed(1):'—';activity.append(el('p',(p.resources_stale?'最近一次资源采样':'实时资源采样')+' · '+cinemaTime(r.time),'muted'),el('p','显存 '+fmt(r.gpu_mib/1024)+' GiB · '+fmt(r.temperature_c??r.gpu_temp)+' °C · '+fmt(r.power_w??r.gpu_watts)+' W · 系统可用 '+fmt(r.available_gib)+' GiB','muted'))}
 activity.append(el('p',p.model+' · 原生画幅 1376 × 768 · 24 fps · 无背景音乐','muted'));
 const sourceNames={script:'白话剧本',story:'原文事实与故事结构',plan:'全章拍摄计划',edit:'导演剪辑方案',timeline:'实际剪辑时间线'};
 const sources=slot('sources');sources.replaceChildren(el('h3','制作资料'),el('p','当前章节独立制作计划与实际剪辑记录。','muted'));const links=el('div',undefined,'row');for(const [key,path] of Object.entries(p.source_files))links.append(cinemaLink(sourceNames[key]||key,path));sources.append(links);
 const review=slot('review');
 // Preserve the video element while polling so playback and seeking continue.
 if(review.dataset.video!==(p.review.video||'')||!review.dataset.initialized){review.replaceChildren(el('h3','全章审片版'));review.dataset.video=p.review.video||'';review.dataset.initialized='true';
 if(p.review.ready){const player=media(p.review.video,'video');player.setAttribute('aria-label','全章审片版播放器');review.append(player);const links=el('div',undefined,'row');links.append(cinemaLink('独立打开全章视频',p.review.video));if(p.review.subtitles)links.append(cinemaLink('白话对白字幕',p.review.subtitles));review.append(links)}else {const pending=el('p',undefined,'muted');pending.dataset.slot='export-note';review.append(pending)}review.append(el('p',undefined,'warn'));}
 const exportNote=review.querySelector('[data-slot="export-note"]');if(exportNote)exportNote.textContent=['failed','interrupted'].includes(p.status)?'导出已停止，请查看当前执行中的错误信息。':'全章视频导出并通过技术检查后，会自动出现在这里。';
 review.querySelector('.warn').textContent=p.review.approved?'整章已人工验收。':'候选生成与声音自动检查不代表影视质量通过。全章仍需人工检查剧情、表演、连贯性、口型与最终声音。';
 cinemaRows(panel,p);
 for(const name of ['kpis','stages','activity','sources','review','shots'])slot(name).hidden=(mode==='content'||mode==='execution'||mode==='episodes')? !['sources','shots'].includes(name):(mode==='review'||mode==='delivery'||mode==='audio')?!['review','kpis','activity'].includes(name):false;
}
async function refreshCinemaPage(){const panel=$('cinemaPage');if(!panel)return;try{const p=await request('/api/production-progress');if(!panel.isConnected)return;if(!p.available){panel.textContent='当前项目尚无新版章节制作任务。';return}renderCinemaDashboard(panel,p,panel.dataset.mode)}catch(e){cinemaConnection(panel,e)}}
function nativeCinemaPage(main,mode){const panel=el('div');panel.id='cinemaPage';panel.dataset.mode=mode;panel.append(el('p','正在读取章节制作记录…','muted'));main.append(panel);refreshCinemaPage()}

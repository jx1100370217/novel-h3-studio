"""Author chapter 2 directly from the novel, with nonverbal arrivals and exact dialogue."""
import math,time
from pathlib import Path
from novel_h3.project import read,write,digest
from novel_h3.timing import semantic_chunks,speech_seconds
from novel_h3.director import frames_for
R=Path(__file__).resolve().parent/'projects/rendao-wuji'
OWNERS={8:'西极勾陈大帝',9:'玉皇大帝',13:'玉皇大帝',14:'北极紫微大帝',15:'西极勾陈大帝',16:'南极长生大帝',17:'东极青华大帝',18:'东华大帝',19:'西王母',20:'华光大帝',21:'东极青华大帝',22:'斗母大帝',23:'玉皇大帝'}
# Each row is an independently motivated shot, not a narration-sized placeholder.
SILENT={
1:[('人间灾变',[],[],6,'wide shot','Two distinct golden trails descend toward the earth. Keep both trajectories readable, then let a tremor ripple through the visible landscape. No words.')],
2:[('人间灾变',[],[],7,'wide shot','Lightning exposes a damaged settlement as roof tiles shake and fall; keep the camera sheltered near ground level.'),('东海',[],[],7,'wide shot','A vast wall of seawater surges toward the coast; hold a stable horizon so the water movement carries the threat.'),('人间灾变',[],[],6,'wide shot','A mountainside fractures and slips into a widening fissure; dust obscures the distance. Do not add named victims or dialogue.')],
3:[('紫微宫',['北极紫微大帝'],[],6,'medium shot','Ziwei steps onto a single golden cloud with an urgent, controlled expression.'),('太微宫外云路',['北极紫微大帝'],[],6,'wide shot','Track the cloud approaching Taiwei Palace; reveal the destination ahead, preserving left-to-right travel.')],
4:[('太微宫外云路',['南极长生大帝','东极青华大帝','西极勾陈大帝'],[],8,'wide shot','Three separate golden clouds approach from different directions and slow near the first arrival. Keep the three emperors distinct.')],
5:[('太微宫外云路',['北极紫微大帝','南极长生大帝','东极青华大帝','西极勾陈大帝'],[],7,'medium shot','The four emperors exchange restrained nods without speaking, then turn together toward the palace entrance.')],
6:[('太微宫',['天兵','北极紫微大帝','南极长生大帝','东极青华大帝','西极勾陈大帝'],[],7,'wide shot','A line of heavenly guards bows as the four emperors pass through the guarded entrance. No greeting is spoken.')],
7:[('太微宫',['玉皇大帝','北极紫微大帝'],['玉笏'],6,'medium shot','The Jade Emperor emerges at the hall threshold holding his tablet and offers a small formal bow; the leading visitor stops opposite him.')],
10:[('太微殿',['玉皇大帝'],['玉笏'],6,'wide shot','The Jade Emperor settles at the raised central throne. Establish the central steps and facing side seats.'),('太微殿',['北极紫微大帝','南极长生大帝','东极青华大帝','西极勾陈大帝'],[],7,'wide shot','The four visitors take the corresponding side seats. Preserve their seating and eyelines for the later debate.')],
11:[('太微宫外云路',['华光大帝','东华大帝'],[],6,'medium shot','Reveal Huaguang and Donghua on separate arriving clouds; preserve their approved bearded and gold-robed identities.'),('太微宫外云路',['斗母大帝','西王母'],[],6,'medium shot','Reveal Doumu and Xiwangmu on the other two clouds. They approach the same entrance without invented dialogue.')],
12:[('太微殿',['玉皇大帝','华光大帝','东华大帝'],['玉笏'],7,'medium shot','The Jade Emperor descends the central steps to receive the arriving emperors.'),('太微殿',['北极紫微大帝','南极长生大帝','东极青华大帝','西极勾陈大帝'],[],5,'medium shot','The seated visitors rise and incline their heads toward the entrance. No additional greeting.')]
}
ACTIONS={8:'Gouchen raises his whisk slightly while offering the formal apology; the Jade Emperor listens.',9:'The Jade Emperor opens a hand toward the hall and invites the visitors inside while speaking.',13:'The Jade Emperor returns up the central steps, takes his throne and addresses the council. Speak only after settling; do not finish the speech while still entering.',14:'Ziwei reports the disorder with increasing concern, looking toward the central throne. Keep the disaster report as his exact dialogue, not a new narrator or fabricated flashback.',15:'Gouchen explains the history of the sea-fixing needle. His hand tightens on the whisk as he reaches the present failure; do not invent a visible historical reenactment.',16:'Nanji leans slightly forward with the short question, then waits.',17:'Qinghua answers with a restrained but definite shake of the head. Keep the other emperors silent.',18:'Donghua refers to the open registered Guangyang register as he explains the disorder; show page disturbance without invented readable sentences.',19:'Xiwangmu holds the registered Anyin register and confirms a similar disorder, looking across the council toward Donghua.',20:'Huaguang speaks with frustrated restraint, holding his posture rather than launching an unmotivated action.',21:'Qinghua turns back toward the throne and reports the reincarnation anomaly. Do not replace the report with new dialogue from the king of reincarnation.',22:'Doumu proposes consulting the Three Pure Ones; let her measured delivery redirect the council.',23:'The Jade Emperor agrees, rises from the throne, then descends the steps at the invitation to leave. Keep the exact full speech audible across the semantic cuts.'}
def run():
 paragraphs=[p for p in read(R/'paragraphs.json') if p['section']=='s0004'];a=read(R/'bible/assets.json');scenes=[];rows=[];source={};audit={};expected=[]
 for p in paragraphs:
  n=int(p['id'].split('_p')[1]);owner=OWNERS.get(n)
  if owner:
   text=p['text'][p['text'].index('“')+1:p['text'].rindex('”')];expected.extend((owner,c) for c in text)
   prop={8:['道尘'],9:['玉笏'],13:['玉笏'],15:['道尘'],18:['光阳仙谱'],19:['暗阴仙谱'],23:['玉笏']}.get(n,[])
   beats=[('太微宫' if n==8 else '太微殿',[owner],prop,max(1,math.ceil(speech_seconds(t)+1)),'medium close-up',ACTIONS[n],t) for t in semantic_chunks(text)]
  else:beats=[(*b,None) for b in SILENT[n]]
  for j,(loc,names,props,seconds,size,action,spoken) in enumerate(beats):
   sid=f'C4D{len(scenes)+1:03d}';utter=[{'kind':'dialogue','speaker':owner,'text':spoken}] if spoken else []
   scene={'scene_id':sid,'duration_seconds':seconds,'segment_break':True,'characters_in_scene':names,'scenes':[loc],'props':props,'scene_description':action,'source_text':spoken or p['text'],'utterances':utter,'needs_replan':False}
   if not spoken:scene['visual_narration']=p['text']
   scenes.append(scene);source[sid]=[p['id']];audit[sid]=[dict(u,source_ids=[p['id']],reason='原文同段明确署名；帝号引号不是对白，只有第8段起的实际发言进入声音列表。') for u in utter]
   refs=[{'asset_id':a[b][name]['id'],'description':name,'lock':'preserve approved identity, wardrobe and geography'} for b,ns in [('characters',names),('scenes',[loc]),('props',props)] for name in ns];assert len(refs)<=9
   frames=frames_for(seconds);h={'location_id':a['scenes'][loc]['id'],'mode':'ref2va','continuity':'cut','seed':640000+len(scenes),'hold_frames':0,'first_frame':None,'last_frame':None,'references':refs,'dramatic_function':'Disaster leads to arrival, council reports and the decision to seek counsel.','action':action,'camera':{'size':size,'lens_mm':65 if spoken else 35,'movement':'locked camera' if spoken else 'slow motivated tracking','motivation':'Read the speaker clearly' if spoken else 'Follow the arrival or physical consequence'},'handoff_in':'Preserve travel direction and the established palace axis.','handoff_out':'Cut after the completed action or semantic clause, keeping seating positions unchanged.','timeline':[{'start_frame':f,'end_frame':min(f+24,frames),'description':action if f==0 else 'Continue the established action. Listeners do not mouth the speaker’s words; no extra dialogue.'} for f in range(0,frames,24)],'soundscape':'No voiceover, no narration, no music. Exact assigned character speech only; restrained environmental and movement sounds.'}
   rows.append({'scene_id':sid,'image_prompt':action,'h3':h,'speech_timing':[{'start_frame':12,'end_frame':12+math.ceil(speech_seconds(spoken)*24)}] if spoken else []})
 assert [(u['speaker'],c) for s in scenes for u in s['utterances'] for c in u['text']]==expected
 assert {p['id'] for p in paragraphs}=={pid for ids in source.values() for pid in ids}
 plan={'id':'chapter_s0004','creative_revision':'dialogue_only_v3','release_role':'episode','dramatic_question':'两道金光为何同时动摇诸界秩序？','turning_point':'九帝无法解释灾变，决定求教三清。','script':{'title':'第二节：四界九帝','scenes':scenes},'source_map':source,'speaker_audit':{'status':'reviewed','reviewer':'Codex 原文逐段审读','scenes':audit},'rhythm_review':{'version':2,'reviewed':False,'source_sequence_verified':True,'status':'new_direction_pending_full_preflight'}}
 write(R/'content_plans/chapter_s0004.json',plan);write(R/'analysis/chapter_s0004_speaker_visual.json',{'content_sha256':digest(plan),'scenes':rows});w=read(R/'analysis/book_rhythm_workorders.json')
 for row in w['chapters']:
  if row['id']==plan['id']:row.update(status='new_draft_written_pending_preflight',shots=len(scenes))
 write(R/'analysis/book_rhythm_workorders.json',w);print('new shots',len(scenes),'source paragraphs',len(paragraphs))
if __name__=='__main__':run()

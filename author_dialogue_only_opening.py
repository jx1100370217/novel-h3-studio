"""New shot authoring from chapter source; no old storyboard input."""
from pathlib import Path
import math
from novel_h3.project import read,write,digest
from novel_h3.timing import semantic_chunks,speech_seconds
from novel_h3.director import frames_for
R=Path(__file__).resolve().parent/'projects/rendao-wuji'
# Source-attributed identities; Pangu identifies himself in paragraph 14.
OWNERS={2:'无极',3:'盘古',4:'无极',5:'盘古',6:'无极',7:'盘古',8:'无极',9:'盘古',10:'无极',11:'盘古',12:'无极',13:'盘古',14:'盘古',15:'无极',16:'盘古',18:'女娲',19:'盘古',20:'女娲',21:'盘古'}
DIRECTIONS={
1:('wide shot',24,'locked camera','A nearly black field holds without speech. A tiny rim of white light grows along the edge of an indistinct silhouette; exposure briefly loses all detail before falling back to darkness. A visual metaphor for light unable to perceive itself, not a spoken explanation.'),
2:('close-up',65,'slow push in','Wuji opens his eyes and searches the darkness. Keep his eyeline screen right toward the unseen answering presence.'),
3:('over-the-shoulder two-shot',50,'gentle reveal from darkness','Reveal Pangu at screen right as the distant answer begins. His light remains restrained; Wuji remains visible in the foreground left, listening with closed lips.'),
4:('close-up',65,'locked camera','Wuji turns toward Pangu, then briefly looks beyond him into empty darkness before completing his question.'),
5:('medium close-up',65,'locked camera','Pangu answers without moving closer. Hold the negative space separating the two figures.'),
6:('close-up',85,'locked camera','Wuji fixes his gaze on the answering figure, asking about identity rather than surveying the space.'),
7:('close-up',85,'locked camera','Pangu gives the short answer with a calm expression; allow a silent beat afterward.'),
8:('close-up',65,'small inward dolly','Wuji raises an open hand toward his own chest, uncertain, without adding a gesture unrelated to his question.'),
9:('medium close-up',65,'locked camera','Pangu looks toward Wuji. Their matching edge light suggests their relationship without multiplying their faces.'),
10:('close-up',85,'locked camera','Wuji lowers his hand, confused and seeking a clearer answer.'),
11:('two-shot',50,'very slow lateral drift','Keep Wuji left and Pangu right. Pangu speaks while Wuji listens with closed lips; the distance remains unchanged.'),
12:('close-up',85,'locked camera','Wuji shakes his head slightly and speaks the short response. Leave room for his expression to settle.'),
13:('over-the-shoulder two-shot',65,'slow push in','Pangu shifts from riddles to a serious explanation of creation and destruction. Wuji remains visible over the near shoulder, listening with closed lips.'),
14:('medium shot',50,'restrained lateral drift','Pangu recounts the origin in an unbroken speaking performance. At semantic cuts change framing between his face and a same-axis two-shot; do not fabricate extra dialogue or literal historical events.'),
15:('close-up',85,'locked camera','Wuji gives the same puzzled response, now quieter, after the long explanation.'),
16:('two-shot',50,'slow pull back','Pangu delivers the decision to send Wuji back. Light gathers subtly around Wuji only toward the end of the entire paragraph; he does not depart early.'),
17:('wide shot',24,'tilt following the departure','A single narrow streak of light leaves Wuji’s position and travels down toward the distant earth. The space he occupied is empty. No words.'),
18:('medium shot',50,'reveal on the established axis','Nuwa becomes visible opposite Pangu after Wuji has departed. She looks toward the fading light trail and asks her question.'),
19:('medium close-up',65,'locked camera','Pangu replies to Nuwa, maintaining the eyeline and the now-empty space where Wuji stood.'),
20:('medium close-up',65,'slow push in','Nuwa speaks with resolved composure. Maintain one face and body while she explains the ten states; do not create ten speaking copies.'),
21:('close-up',85,'slow pull back','Pangu finishes his farewell while facing Nuwa. His outline softens into the surrounding light, without an extra line.'),
22:('wide shot',24,'locked camera','A second streak leaves Nuwa’s position. Hold the empty composition after it vanishes, then let the remaining outline dissolve into black. No speech and no music.')}
def run():
 paras=[p for p in read(R/'paragraphs.json') if p['section']=='s0003'];assets=read(R/'bible/assets.json');scenes=[];visual=[];audit={};source_map={}
 for p in paras:
  n=int(p['id'].split('_p')[1]);owner=OWNERS.get(n);text=p['text'];spoken=text[text.index('“')+1:text.rindex('”')] if owner else None
  parts=semantic_chunks(spoken) if owner else [None]
  for j,part in enumerate(parts):
   sid=f'C3D{len(scenes)+1:03d}';size,lens,move,action=DIRECTIONS[n];seconds=max(1,math.ceil(speech_seconds(part)+1)) if part else {1:8,17:6,22:7}[n]
   # The opening is an abstract field of light and an indistinct silhouette.
   # Do not bind Wuji's two-view identity sheet until he is visibly revealed.
   names=([owner] if owner else [])
   if 3 <= n <= 16:names=['无极','盘古']
   if 18 <= n <= 21:names=['盘古','女娲']
   if n==14 and j%2==1:names=['无极','盘古'];size='two-shot'
   utter=[{'kind':'dialogue','speaker':owner,'text':part}] if part else []
   scene={'scene_id':sid,'duration_seconds':seconds,'segment_break':True,'characters_in_scene':names,'scenes':['天外天'],'props':[],'scene_description':action,'utterances':utter,'source_text':part if part else text,'needs_replan':False}
   if not part:scene['visual_narration']=text
   scenes.append(scene);source_map[sid]=[p['id']];audit[sid]=[dict(u,source_ids=[p['id']],reason='逐段审读：稚嫩声音为无极；第14段明确盘古身份；无极离去后女娲与盘古对话。') for u in utter]
   frames=frames_for(seconds);refs=[{'asset_id':assets['characters'][name]['id'],'description':name,'lock':'preserve approved identity and costume'} for name in names]+[{'asset_id':'outer_heaven','description':'天外天','lock':'preserve spatial appearance'}]
   continuation=('Continue the established performance and camera move. Only the assigned character speaks; listeners remain silent.'
                 if part else 'Continue the established visual action and camera move. No person speaks and no words are audible.')
   soundscape=('No narration, no voiceover, no music. Only the assigned exact character dialogue and restrained movement sounds.'
               if part else 'Absolute digital silence. No speech, narration, voiceover, ambience, music or sound effects.')
   h={'location_id':'outer_heaven','mode':'ref2va','continuity':'cut','seed':630000+len(scenes),'hold_frames':0,'first_frame':None,'last_frame':None,'references':refs,'dramatic_function':'Identity inquiry' if n<13 else 'Origin, decision and departure','action':action,'camera':{'size':size,'lens_mm':lens,'movement':move,'motivation':'Follow the question, revelation or change in intention'},'handoff_in':'Maintain left-right eyelines from the preceding shot.','handoff_out':'Cut at the completed semantic beat; preserve posture and screen direction.','timeline':[{'start_frame':f,'end_frame':min(f+24,frames),'description':action if f==0 else continuation} for f in range(0,frames,24)],'soundscape':soundscape}
   visual.append({'scene_id':sid,'image_prompt':action,'h3':h,'speech_timing':[{'start_frame':12,'end_frame':12+math.ceil(speech_seconds(part)*24)}] if part else []})
 plan={'id':'chapter_s0003','creative_revision':'dialogue_only_v3','release_role':'episode','dramatic_question':'无极是谁，为何必须再次进入轮回？','turning_point':'盘古送无极返世，女娲随后离去，天外天重归寂静。','script':{'title':'第一节：创世三皇','scenes':scenes},'source_map':source_map,'speaker_audit':{'status':'reviewed','reviewer':'Codex 原文逐段审读','scenes':audit},'rhythm_review':{'version':2,'reviewed':False,'source_sequence_verified':True,'status':'new_direction_pending_full_preflight'}}
 expected=[(OWNERS[int(p['id'].split('_p')[1])],p['text'][p['text'].index('“')+1:p['text'].rindex('”')]) for p in paras if int(p['id'].split('_p')[1]) in OWNERS]
 assert [(u['speaker'],ch) for s in scenes for u in s['utterances'] for ch in u['text']]==[(name,ch) for name,words in expected for ch in words]
 assert {x for ids in source_map.values() for x in ids}=={p['id'] for p in paras}
 write(R/'content_plans/chapter_s0003.json',plan);write(R/'analysis/chapter_s0003_speaker_visual.json',{'content_sha256':digest(plan),'scenes':visual})
 w=read(R/'analysis/book_rhythm_workorders.json');w['chapters'][0].update(status='new_draft_written_pending_preflight',shots=len(scenes));write(R/'analysis/book_rhythm_workorders.json',w);print('new shots',len(scenes),'spoken lines',sum(bool(s['utterances']) for s in scenes))
if __name__=='__main__':run()

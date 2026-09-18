"""CPU-only reference transcription candidates; never approve voices."""
from pathlib import Path
from novel_h3.project import read,write,file_hash
from audio_review import decode_audio,model_path
import soundfile as sf
import torch
from transformers import WhisperForConditionalGeneration,WhisperProcessor,pipeline
r=Path(__file__).parent/'projects/rendao-wuji';out=r/'analysis/cast_transcripts';out.mkdir(exist_ok=True)
torch.set_num_threads(2)
m=WhisperForConditionalGeneration.from_pretrained(model_path('speech'),local_files_only=True,dtype=torch.float32)
p=WhisperProcessor.from_pretrained(model_path('speech'),local_files_only=True)
pipe=pipeline('automatic-speech-recognition',model=m,tokenizer=p.tokenizer,feature_extractor=p.feature_extractor,device='cpu')
audit=read(r/'analysis/rhythm_candidates/chapter_s0004_voice_technical_audit.json')
for v in audit['voices']:
 name=v['character'];source=r/v['path'];target=out/(name+'.json')
 if target.exists() and read(target).get('sha256')==file_hash(source):continue
 wav=out/(name+'.wav');decode_audio(source,wav);x,sr=sf.read(wav,dtype='float32')
 result=pipe({'raw':x,'sampling_rate':sr},return_timestamps=True,generate_kwargs={'language':'zh','task':'transcribe'})
 write(target,{'character':name,'source':v['path'],'sha256':file_hash(source),'recognition':result,'status':'machine_transcript_pending_listening','approved':False});print(name,result['text'],flush=True)

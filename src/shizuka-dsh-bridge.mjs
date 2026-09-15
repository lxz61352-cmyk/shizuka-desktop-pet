// Task-local DSH observer and native user-question provider. No server or global profile changes.
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
export const name='shizuka-task-bridge';
export const inject=['userQuestions','sessions','agentDefaultModel'];
const scrub=value=>String(value).replace(/sk-[A-Za-z0-9_-]{16,}/g,'[已隐藏密钥]')
  .replace(/(Bearer\s+)[A-Za-z0-9._~-]+/gi,'$1[已隐藏]');
export function apply(ctx){
  const directory=process.env.SHIZUKA_DSH_TASK_DIR;
  if(!directory)throw new Error('Missing task-local bridge directory');
  const eventFile=path.join(directory,'events.jsonl');
  let rootSession=null;
  const emit=value=>fs.appendFileSync(eventFile,JSON.stringify({time:Date.now()/1000,...value})+'\n','utf8');
  // Change only the model of this pet-owned process. Never save a global DSH setting.
  const selectedModel=process.env.SHIZUKA_DSH_MODEL;
  if(['deepseek-v4-pro','deepseek-flash'].includes(selectedModel)){
    const original=ctx.agentDefaultModel.currentSelection.bind(ctx.agentDefaultModel);
    ctx.agentDefaultModel.currentSelection=()=>{
      const selection=original();
      return selection.provider==='deepseek-official'?{...selection,model:selectedModel}:selection;
    };
    emit({type:'model',text:'本轮模型：'+selectedModel});
  }
  ctx.on('session/event',(session,event)=>{
    if(event.type==='turn/start' && rootSession===null){rootSession=session.id;emit({type:'session',session_id:rootSession});}
    if(rootSession!==session.id)return;
    const data=event.data;
    if(event.type==='step/start')emit({type:'step',step:data.step,text:'正在判断下一步'});
    if(event.type==='assistant/chunk' && data.chunk.type==='text-delta')emit({type:'text',text:scrub(data.chunk.text)});
    if(event.type==='tool/call')emit({type:'tool_call',name:data.name,call_id:data.callId,text:scrub(data.arguments).slice(0,16000)});
    if(event.type==='tool/result'){
      const message=data.message;
      const text=(message.content??[]).map(block=>block.type==='text'?block.text:'').join('\n');
      emit({type:'tool_result',call_id:message.callId??message.toolCallId,text:scrub(text).slice(0,24000),error:data.error?.code??null});
    }
    if(event.type==='turn/end')emit({type:'turn_end',reason:data.reason?.kind??'unknown'});
  });
  ctx.userQuestions.registerProvider({ask(request){
    const id=randomUUID();const file=path.join(directory,'answer-'+id+'.json');
    emit({type:'question',request_id:id,questions:request.questions});
    return new Promise((resolve,reject)=>{
      let timer;
      const done=(error,value)=>{clearInterval(timer);request.signal?.removeEventListener('abort',abort);if(error)reject(error);else resolve(value);};
      const abort=()=>{emit({type:'question_cancelled',request_id:id});done(new Error('User question cancelled'));};
      request.signal?.addEventListener('abort',abort,{once:true});
      timer=setInterval(()=>{
        if(!fs.existsSync(file))return;
        try{
          const value=JSON.parse(fs.readFileSync(file,'utf8'));
          if(!Array.isArray(value.answers) || value.answers.length!==request.questions.length)throw new Error('Invalid answer count');
          if(value.answers.some((answer,i)=>answer.id!==request.questions[i].id || !Array.isArray(answer.selected)))throw new Error('Answer IDs do not match');
          emit({type:'question_answered',request_id:id});done(null,value);
        }catch(error){done(error);}
      },150);
      if(request.signal?.aborted)abort();
    });
  }});
  emit({type:'bridge_ready',text:'实时执行记录已连接'});
}

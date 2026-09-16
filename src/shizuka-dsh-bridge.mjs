// Task-local DSH observer and native user-question provider. No server or global profile changes.
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
export const name='shizuka-task-bridge';
export const inject=['userQuestions','sessions','agentDefaultModel'];
const ANSWER_WAIT_MS=30*60*1000;   // 等用户回答的上限：超时就收场，别让定时器和 Promise 一直挂着
const scrub=value=>String(value).replace(/sk-[A-Za-z0-9_-]{16,}/g,'[已隐藏密钥]')
  .replace(/(Bearer\s+)[A-Za-z0-9._~-]+/gi,'$1[已隐藏]');
export function apply(ctx){
  const directory=process.env.SHIZUKA_DSH_TASK_DIR;
  // 宁可这条 bridge 静默失效，也不能让 apply 抛错：DSH 会把抛错的插件判为 FIBER_FAILED，
  // 整棵插件树和这次任务一起失败。
  if(!directory)return;
  const eventFile=path.join(directory,'events.jsonl');
  let rootSession=null;
  const emit=value=>{try{fs.appendFileSync(eventFile,JSON.stringify({time:Date.now()/1000,...value})+'\n','utf8');}catch{}};
  const warn=(where,error)=>emit({type:'bridge_warning',text:where+'未接上：'+scrub(error?.message??error)});
  // Change only the model of this pet-owned process. Never save a global DSH setting.
  const selectedModel=process.env.SHIZUKA_DSH_MODEL;
  try{
    // 具体模型名由桌宠决定（api_runtime.DEEPSEEK_MODEL 一处定义），这里不再维护白名单
    if(selectedModel && typeof ctx.agentDefaultModel?.currentSelection==='function'){
      const original=ctx.agentDefaultModel.currentSelection.bind(ctx.agentDefaultModel);
      ctx.agentDefaultModel.currentSelection=()=>{
        const selection=original()||{};
        return selection.provider==='deepseek-official'?{...selection,model:selectedModel}:selection;
      };
      emit({type:'model',text:'本轮模型：'+selectedModel});
    }
  }catch(error){warn('模型切换',error);}
  try{
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
        emit({type:'tool_result',call_id:message.callId??message.source?.callId??message.toolCallId,text:scrub(text).slice(0,24000),error:data.error?.code??null});
      }
      if(event.type==='turn/end')emit({type:'turn_end',reason:data.reason?.kind??'unknown'});
    });
  }catch(error){warn('执行记录',error);}
  // 原生提问通道：DSH 改过 API（旧 registerProvider / 新 user-questions/request waterfall），
  // 两个都试；接不上只记一条警告，不能让插件树整体失败、把任务也带崩。
  const answer=request=>{
    const id=randomUUID();const file=path.join(directory,'answer-'+id+'.json');
    emit({type:'question',request_id:id,questions:request.questions});
    return new Promise((resolve,reject)=>{
      let timer;
      const done=(error,value)=>{
        if(timer)clearInterval(timer);
        request.signal?.removeEventListener('abort',abort);
        if(error)reject(error);else resolve(value);
      };
      const abort=()=>{emit({type:'question_cancelled',request_id:id});done(new Error('User question cancelled'));};
      request.signal?.addEventListener('abort',abort,{once:true});
      const deadline=Date.now()+ANSWER_WAIT_MS;
      timer=setInterval(()=>{
        // 没人回答也要能收场：超时、答案文件非法都发 question_cancelled，
        // 否则桌宠端会一直以为「正在等待回答」，任务时限也不再计时。
        if(Date.now()>deadline){emit({type:'question_cancelled',request_id:id});done(new Error('User question timed out'));return;}
        if(!fs.existsSync(file))return;
        try{
          const value=JSON.parse(fs.readFileSync(file,'utf8'));
          if(!Array.isArray(value.answers) || value.answers.length!==request.questions.length)throw new Error('Invalid answer count');
          if(value.answers.some((answer,i)=>answer.id!==request.questions[i].id || !Array.isArray(answer.selected)))throw new Error('Answer IDs do not match');
          emit({type:'question_answered',request_id:id});done(null,value);
        }catch(error){emit({type:'question_cancelled',request_id:id});done(error);}
      },150);
      if(request.signal?.aborted)abort();
    });
  };
  let channel='none';
  try{
    if(typeof ctx.userQuestions?.registerProvider==='function'){
      ctx.userQuestions.registerProvider({ask:answer});channel='registerProvider';
    }else if(typeof ctx.on==='function'){
      ctx.on('user-questions/request',(request,next)=>answer(request));channel='waterfall';
    }else{
      throw new Error('userQuestions 与 ctx.on 都不可用');
    }
  }catch(error){warn('提问通道',error);}
  emit({type:'bridge_ready',text:'实时执行记录已连接',channel});
}

// Experiment transport adapter only. The existing JPEG decode/paint/report path is reused.
export function unpack(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength<4) throw Error('bad packet');
  const length=new DataView(buffer).getUint32(0);
  if(length>8192 || length+4>buffer.byteLength)throw Error('bad metadata length');
  const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,length)));
  if(!Number.isInteger(meta.status)||!meta.headers)throw Error('bad metadata');
  return {ok:meta.status===200,status:meta.status,headers:new Headers(meta.headers),blob:async()=>new Blob([buffer.slice(4+length)],{type:'image/jpeg'})};
}

export function websocketFetcher(base, endpoint) {
  let socket=null, pending=null, disposed=false;
  const fail=error=>{const p=pending;pending=null;if(p){p.cleanup();p.reject(error);} };
  const close=()=>{const old=socket;socket=null;old?.close();};
  function request(url,options={}) {
    if(disposed)return Promise.reject(Error('disposed'));
    if(pending)return Promise.reject(Error('overlapping image request'));
    if(options.signal?.aborted)return Promise.reject(Error('aborted'));
    const u=new URL(url,'http://127.0.0.1');
    const body=JSON.stringify({session:u.searchParams.get('session')||'',after:Number(u.searchParams.get('after')||0)});
    return new Promise((resolve,reject)=>{
      const abort=()=>{fail(Error('aborted'));close();};
      pending={resolve,reject,cleanup:()=>options.signal?.removeEventListener('abort',abort),body};
      options.signal?.addEventListener('abort',abort,{once:true});
      if(!socket){
        const ws=socket=new base.WebSocket(endpoint);ws.binaryType='arraybuffer';
        ws.onopen=()=>{if(ws===socket && pending)ws.send(pending.body);};
        ws.onmessage=event=>{if(ws!==socket||!pending)return;try{const response=unpack(event.data);const p=pending;pending=null;p.cleanup();p.resolve(response);}catch(e){fail(e);close();}};
        ws.onerror=()=>{if(ws===socket){fail(Error('websocket error'));close();}};
        ws.onclose=()=>{if(ws===socket){socket=null;fail(Error('websocket closed'));}};
      }else if(socket.readyState===1)socket.send(body);
    });
  }
  return {fetch:request,disconnect(){fail(Error('injected disconnect'));close();},dispose(){disposed=true;fail(Error('disposed'));close();}};
}

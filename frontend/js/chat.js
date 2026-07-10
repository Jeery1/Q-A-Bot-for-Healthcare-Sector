const { createApp, ref, reactive, nextTick, watch, onMounted } = Vue;

createApp({
  setup(){
    const chatRef = ref(null);
    const messages = reactive([]);
    const status = ref('idle');
    const wsMode = ref('w2');
    const isRecording = ref(false);
    const audioPaused = ref(false);
    const audioPlaying = ref(false);
    const inputText = ref('');

    const modes = [
      {key:'w2',label:'W2 全流式'},
      {key:'w3',label:'W3 安全'},
    ];

    const statusText = ref('就绪');
    const statusClass = ref('idle');

    const user = reactive({id:null,username:''});

    const toast = reactive({show:false,text:'',type:'error'});
    let toastTimer = null;

    function showToast(text, type='error'){
      clearTimeout(toastTimer);
      toast.text = text; toast.type = type; toast.show = true;
      toastTimer = setTimeout(()=>toast.show=false, 3000);
    }

    const accessToken = ref(localStorage.getItem('access_token')||'');
    if(!accessToken.value){
      location.replace('/login.html');
    } else {
      try{
        const payload = JSON.parse(atob(accessToken.value.split('.')[1]));
        if(payload.exp * 1000 < Date.now()){
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          localStorage.removeItem('user');
          location.replace('/login.html');
        }
      }catch(e){
        location.replace('/login.html');
      }
    }
    try{
      const u = JSON.parse(localStorage.getItem('user')||'{}');
      user.id = u.id; user.username = u.username;
    }catch(e){}

    let refreshTimer = null;

    function getTokenPayload(token){
      try{ return JSON.parse(atob(token.split('.')[1])); }catch(e){ return null; }
    }

    async function refreshToken(){
      const rt = localStorage.getItem('refresh_token');
      if(!rt) throw new Error('no refresh token');
      const r = await fetch('/api/auth/refresh',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({refresh_token:rt})
      });
      if(!r.ok){
        if(r.status === 429){
          const d = await r.json();
          showToast(d.detail||'请求过于频繁');
        }
        throw new Error('refresh failed');
      }
      const data = await r.json();
      accessToken.value = data.access_token;
      localStorage.setItem('access_token',data.access_token);
      localStorage.setItem('refresh_token',data.refresh_token);
      scheduleTokenRefresh();
    }

    function scheduleTokenRefresh(){
      if(refreshTimer) clearTimeout(refreshTimer);
      const payload = getTokenPayload(accessToken.value);
      if(!payload || !payload.exp) return;
      const expiresAt = payload.exp * 1000;
      const delay = expiresAt - Date.now() - 60000;
      if(delay <= 0){
        refreshToken().catch(()=>doLogout());
      }else{
        refreshTimer = setTimeout(() => refreshToken().catch(()=>doLogout()), delay);
      }
    }

    scheduleTokenRefresh();

    const conversations = ref([]);
    const convId = ref(0);

    async function loadConversations(){
      try{
        const r = await fetch('/api/conversations?archived=0&size=50',{
          headers:{Authorization:'Bearer '+accessToken.value}
        });
        if(!r.ok){
          if(r.status === 429){
            const d = await r.json();
            showToast(d.detail||'请求过于频繁');
          }
          return;
        }
        conversations.value = await r.json();
      }catch(e){}
    }

    function fmtTime(ts){
      if(!ts) return '';
      const d = new Date(ts);
      const now = new Date();
      const diff = now - d;
      if(diff < 60000) return '刚刚';
      if(diff < 3600000) return Math.floor(diff/60000)+'分钟前';
      if(diff < 86400000) return Math.floor(diff/3600000)+'小时前';
      return d.getMonth()+1+'/'+d.getDate()+' '+d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
    }

    function switchConv(id){
      stopAudio();
      convId.value = id;
      messages.splice(0, messages.length);
      if(tmpMsgIdx >= 0) tmpMsgIdx = -1;
      reconnectCount = 0;
      connect(wsMode.value);
      loadMessages(id);
    }

    function newConversation(){
      stopAudio();
      convId.value = 0;
      messages.splice(0, messages.length);
      if(tmpMsgIdx >= 0) tmpMsgIdx = -1;
      reconnectCount = 0;
      connect(wsMode.value);
    }

    async function deleteConv(id){
      try{
        const r = await fetch('/api/conversations/'+id,{
          method:'DELETE',
          headers:{Authorization:'Bearer '+accessToken.value}
        });
        if(!r.ok){
          if(r.status === 429){
            const d = await r.json();
            showToast(d.detail||'请求过于频繁');
          }
          return;
        }
        conversations.value = conversations.value.filter(c=>c.id!==id);
        if(convId.value === id){
          convId.value = 0;
          messages.splice(0, messages.length);
        }
      }catch(e){}
    }

    async function loadMessages(conv_id){
      try{
        const r = await fetch('/api/conversations/'+conv_id+'/messages',{
          headers:{Authorization:'Bearer '+accessToken.value}
        });
        if(!r.ok){
          if(r.status === 429){
            const d = await r.json();
            showToast(d.detail||'请求过于频繁');
          }
          return;
        }
        const msgs = await r.json();
        messages.splice(0, messages.length);
        msgs.forEach(m => {
          if(m.role === 'user'){
            messages.push({text:m.content,cls:'asr-final',label:'您说:'});
          }else{
            if(m.search_results && m.search_results.length){
              messages.push({cls:'rag', docs: m.search_results, expanded: false});
            }
            messages.push({text:m.content,cls:'bot',label:'AI:'});
          }
        });
        nextTick(()=>scrollDown());
      }catch(e){}
    }

    function doLogout(){
      if(refreshTimer) clearTimeout(refreshTimer);
      authExpired = true;
      clearReconnect();
      stopAudio();
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user');
      setTimeout(() => location.replace('/login.html'), 0);
    }

    let ws = null, audioCtx = null, source = null, processor = null, stream = null;
    let audioQueue = [], currentAudio = null;
    let tmpMsgIdx = -1;
    let reconnectTimer = null, reconnectCount = 0, authExpired = false;

    function clearReconnect(){
      if(reconnectTimer){ clearTimeout(reconnectTimer); reconnectTimer = null; }
    }

    function scheduleReconnect(){
      if(authExpired) return;
      clearReconnect();
      reconnectCount++;
      const base = Math.min(1000 * Math.pow(2, reconnectCount-1), 16000);
      const delay = Math.floor(base * (0.5 + Math.random() * 0.5));
      setStatus('重连中('+reconnectCount+')…','disconnected');
      reconnectTimer = setTimeout(() => connect(wsMode.value), delay);
    }

    function setStatus(t,c){
      status.value = c;
      statusText.value = t;
      statusClass.value = c;
    }

    function addMsg(text,cls,label){
      messages.push({text,cls,label:label||''});
      scrollDown();
    }

    function scrollDown(){
      nextTick(()=>{
        if(chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight;
      });
    }

    function connect(m){
      clearReconnect();
      if(ws){ try{ws.close()}catch(e){}; ws = null; }
      wsMode.value = m;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const socket = ws = new WebSocket(proto+'://'+location.host+'/ws?mode='+m+'&token='+accessToken.value+'&conv_id='+convId.value);
      socket.onopen = () => { reconnectCount = 0; setStatus('就绪','idle'); };
      socket.onclose = () => { if(ws !== socket) return; scheduleReconnect(); };
      socket.onmessage = onMsg;
      socket.onerror = () => {};
    }

    function onMsg(e){
      const d = JSON.parse(e.data);
      if(d.error){
        if(d.error.includes('认证')||d.error.includes('登录')||d.error.includes('令牌')){
          authExpired = true;
          doLogout();
          return;
        }
        addMsg('错误: '+d.error,'bot','');
        setStatus('就绪','idle');
        return;
      }
      if(d.type === 'asr_partial'){
        if(tmpMsgIdx < 0){
          messages.push({text:d.text,cls:'asr-partial',label:'正在聆听'});
          tmpMsgIdx = messages.length-1;
        }else{
          messages[tmpMsgIdx].text = d.text;
        }
        scrollDown();
      }else if(d.type === 'asr_final'){
        if(tmpMsgIdx >= 0){ messages.splice(tmpMsgIdx,1); tmpMsgIdx=-1; }
        addMsg(d.text,'asr-final','您说:');
      }else if(d.type === 'llm_token'){
        const last = messages.length>0 ? messages[messages.length-1] : null;
        if(!last || last.cls !== 'llm-token'){
          messages.push({text:'',cls:'llm-token',label:'AI'});
        }
        const cur = messages[messages.length-1];
        cur.text += d.text;
        scrollDown();
      }else if(d.type === 'answer'){
        if(tmpMsgIdx >= 0){ messages.splice(tmpMsgIdx,1); tmpMsgIdx=-1; }
        const cls = d.safe===false ? 'security' : 'bot';
        addMsg(d.text,cls,d.safe===false ? '安全提醒:' : 'AI:');
      }else if(d.type === 'tts_chunk'){
        playAudio(d.data);
      }else if(d.type === 'audio'){
        playAudio(d.data);
        setStatus('就绪','idle');
      }else if(d.type === 'done'){
        setStatus('就绪','idle');
        audioPaused.value = false;
        loadConversations();
      }else if(d.type === 'conv_created'){
        convId.value = d.conv_id;
        loadConversations();
      }else if(d.type === 'rag_info'){
        messages.push({cls:'rag', docs: d.docs||[], expanded: false});
        scrollDown();
      }
    }

    function stopAudio(){
      audioQueue = [];
      audioPlaying.value = false;
      audioPaused.value = false;
      if(currentAudio){
        try{ currentAudio.pause(); }catch(e){}
        currentAudio = null;
      }
    }

    function playAudio(b64){
      audioQueue.push(b64);
      if(!audioPlaying.value) _playNext();
    }
    function _playNext(){
      if(audioPaused.value) return;
      if(!audioQueue.length){ audioPlaying.value=false; currentAudio=null; return; }
      audioPlaying.value = true;
      const bin = Uint8Array.from(atob(audioQueue.shift()),c=>c.charCodeAt(0));
      const blob = new Blob([bin],{type:'audio/wav'});
      const url = URL.createObjectURL(blob);
      const a = new Audio(url);
      currentAudio = a;
      a.onended = ()=>{ URL.revokeObjectURL(url); _playNext(); };
      a.play().catch(()=>_playNext());
    }

    function togglePause(){
      if(!currentAudio) return;
      if(audioPaused.value){
        audioPaused.value = false;
        currentAudio.play().catch(()=>{});
      }else{
        audioPaused.value = true;
        currentAudio.pause();
      }
    }

    function sendText(){
      const t = inputText.value.trim();
      if(!t || !ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({type:'text_query',text:t}));
      inputText.value = '';
      setStatus('处理中…','processing');
    }

    async function startRec(){
      if(!ws || ws.readyState !== WebSocket.OPEN) return;
      try{
        stream = await navigator.mediaDevices.getUserMedia({
          audio:{sampleRate:16000,channelCount:1}
        });
        audioCtx = new (window.AudioContext||window.webkitAudioContext)({sampleRate:16000});
        source = audioCtx.createMediaStreamSource(stream);
        const bufLen = 2048;
        processor = audioCtx.createScriptProcessor(bufLen,1,1);
        isRecording.value = true;
        processor.onaudioprocess = e => {
          if(!isRecording.value) return;
          const input = e.inputBuffer.getChannelData(0);
          const pcm = new Int16Array(input.length);
          for(let i=0;i<input.length;i++){
            const s = Math.max(-1,Math.min(1,input[i]));
            pcm[i] = s<0 ? s*32768 : s*32767;
          }
          if(ws && ws.readyState===WebSocket.OPEN) ws.send(pcm.buffer);
        };
        source.connect(processor);
        processor.connect(audioCtx.destination);
        setStatus('录音中…','recording');
      }catch(e){
        addMsg('麦克风不可用: '+e.message,'bot','');
      }
    }

    function stopRec(){
      isRecording.value = false;
      if(processor){ processor.disconnect(); processor=null; }
      if(source){ source.disconnect(); source=null; }
      if(audioCtx){ audioCtx.close(); audioCtx=null; }
      if(stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; }
      audioQueue = []; audioPlaying.value = false; audioPaused.value = false;
      if(currentAudio){ try{currentAudio.pause()}catch(e){}; currentAudio=null; }
      if(ws && ws.readyState===WebSocket.OPEN) ws.send(JSON.stringify({type:'audio_end'}));
      setStatus('处理中…','processing');
    }

    function stopRecIfRecording(){
      if(isRecording.value) stopRec();
    }

    function switchMode(m){
      wsMode.value = m;
      connect(m);
      for(let i=messages.length-1;i>=0;i--){
        if(messages[i].cls==='system') messages.splice(i,1);
      }
      addMsg('已切换到 '+modes.find(x=>x.key===m).label,'system','');
      if(tmpMsgIdx >= 0){ messages.splice(tmpMsgIdx,1); tmpMsgIdx=-1; }
      const idx = messages.length - 1;
      setTimeout(()=>{ if(messages[idx]?.cls==='system') messages.splice(idx,1); }, 2500);
    }

    onMounted(()=>{
      loadConversations();
      connect('w2');
    });

    return {
      chatRef, messages, status, wsMode, isRecording,
      audioPaused, audioPlaying, togglePause, toast,
      inputText, sendText, user, doLogout,
      modes, statusText, statusClass,
      startRec, stopRec, stopRecIfRecording, switchMode,
      conversations, convId, loadConversations, loadMessages,
      fmtTime, switchConv, newConversation, deleteConv,
    };
  }
}).mount('#vue-app');

const { createApp, ref, reactive } = Vue;

const API = {
  async call(path, body){
    const r = await fetch(path, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    const data = await r.json();
    if(!r.ok) throw new Error(data.detail||'请求失败');
    return data;
  }
};

createApp({
  setup(){
    const tab = ref('login');
    const loginLoading = ref(false);
    const registerLoading = ref(false);

    const loginForm = reactive({username:'',password:''});
    const loginErrors = reactive({username:'',password:''});

    const registerForm = reactive({username:'',password:'',confirm:''});
    const registerErrors = reactive({username:'',password:'',confirm:''});

    const toast = reactive({show:false,text:'',type:'success'});
    let toastTimer = null;

    function showToast(text, type='success'){
      clearTimeout(toastTimer);
      toast.text = text; toast.type = type; toast.show = true;
      toastTimer = setTimeout(()=>toast.show=false, 2500);
    }

    function switchTab(t){
      tab.value = t;
      clearErrors();
    }

    function clearErrors(){
      Object.keys(loginErrors).forEach(k=>loginErrors[k]='');
      Object.keys(registerErrors).forEach(k=>registerErrors[k]='');
    }

    function validateLogin(){
      let ok = true;
      clearErrors();
      if(!loginForm.username.trim()){
        loginErrors.username = '请输入用户名'; ok = false;
      }
      if(!loginForm.password){
        loginErrors.password = '请输入密码'; ok = false;
      }
      return ok;
    }

    function validateRegister(){
      let ok = true;
      clearErrors();
      if(!registerForm.username.trim() || registerForm.username.trim().length<3){
        registerErrors.username = '用户名至少3个字符'; ok = false;
      }
      if(!registerForm.password || registerForm.password.length<6){
        registerErrors.password = '密码至少6个字符'; ok = false;
      }
      if(registerForm.password !== registerForm.confirm){
        registerErrors.confirm = '两次密码不一致'; ok = false;
      }
      return ok;
    }

    async function doLogin(){
      if(!validateLogin()) return;
      loginLoading.value = true;
      try{
        const data = await API.call('/api/auth/login',{
          username:loginForm.username.trim(),
          password:loginForm.password
        });
        localStorage.setItem('access_token',data.access_token);
        localStorage.setItem('refresh_token',data.refresh_token);
        localStorage.setItem('user',JSON.stringify(data.user));
        window.location.href = '/';
      }catch(e){
        showToast(e.message,'error');
      }finally{
        loginLoading.value = false;
      }
    }

    async function doRegister(){
      if(!validateRegister()) return;
      registerLoading.value = true;
      try{
        const data = await API.call('/api/auth/register',{
          username:registerForm.username.trim(),
          password:registerForm.password
        });
        localStorage.setItem('access_token',data.access_token);
        localStorage.setItem('refresh_token',data.refresh_token);
        localStorage.setItem('user',JSON.stringify(data.user));
        window.location.href = '/';
      }catch(e){
        showToast(e.message,'error');
      }finally{
        registerLoading.value = false;
      }
    }

    return {
      tab, loginForm, loginErrors, registerForm, registerErrors,
      loginLoading, registerLoading, toast,
      switchTab, doLogin, doRegister
    };
  }
}).mount('#app');

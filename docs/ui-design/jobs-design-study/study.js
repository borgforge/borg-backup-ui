(() => {
  const q=new URLSearchParams(location.search);
  const variant=['a','b','c'].includes(q.get('v'))?q.get('v'):'a';
  document.querySelectorAll('.variant').forEach(x=>x.classList.toggle('active',x.dataset.variant===variant));
  document.querySelectorAll('[data-variant-choice]').forEach(x=>{
    x.classList.toggle('active',x.dataset.variantChoice===variant);
    x.addEventListener('click',()=>{q.set('v',x.dataset.variantChoice);location.search=q.toString()});
  });
  const requested=q.get('theme');
  document.documentElement.dataset.theme=['light','dark'].includes(requested)?requested:(localStorage.getItem('jobs-study-theme')||'dark');
  const theme=document.getElementById('theme-toggle');
  const sync=()=>theme.textContent=document.documentElement.dataset.theme==='dark'?'☀':'☾';
  sync();
  theme.addEventListener('click',()=>{
    const next=document.documentElement.dataset.theme==='dark'?'light':'dark';
    document.documentElement.dataset.theme=next;
    localStorage.setItem('jobs-study-theme',next);
    sync();
  });
})();

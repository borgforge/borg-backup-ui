/* Locally bundled Bash highlighting over a native, accessible textarea (#550). */
(function () {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};

  /**
   * Enhance a textarea without changing its value, label, submission or undo.
   * Returns setError(line) for Bash diagnostics and destroy() for panel teardown.
   * Highlighting is visual only; syntax validation remains on the server.
   */
  function create(textarea) {
    const shell = document.createElement('div');
    shell.className = 'bash-editor';
    const gutter = document.createElement('div');
    gutter.className = 'bash-editor-gutter';
    gutter.setAttribute('aria-hidden', 'true');
    const numbers = document.createElement('div');
    gutter.append(numbers);
    const code = document.createElement('div');
    code.className = 'bash-editor-code';
    const highlight = document.createElement('pre');
    highlight.className = 'bash-editor-highlight';
    highlight.setAttribute('aria-hidden', 'true');
    textarea.before(shell);
    shell.append(gutter, code);
    code.append(highlight, textarea);
    textarea.classList.add('bash-editor-input');
    textarea.wrap = 'off';
    textarea.autocomplete = 'off';
    textarea.setAttribute('autocorrect', 'off');
    let timer;
    let errorLine = 0;

    function syncScroll() {
      highlight.style.width = `${textarea.clientWidth}px`;
      highlight.style.height = `${textarea.clientHeight}px`;
      highlight.scrollTop = textarea.scrollTop;
      highlight.scrollLeft = textarea.scrollLeft;
      numbers.style.transform = `translateY(${-textarea.scrollTop}px)`;
    }

    function render() {
      const source = textarea.value;
      const grammar = window.Prism?.languages?.bash;
      if (grammar && new Blob([source]).size <= 65536) {
        highlight.innerHTML = window.Prism.highlight(source + '\n', grammar, 'bash');
        shell.classList.add('has-highlighting');
      } else {
        highlight.textContent = '';
        shell.classList.remove('has-highlighting');
      }
      numbers.replaceChildren(...source.split('\n').map((_, index) => {
        const number = document.createElement('span');
        number.textContent = String(index + 1);
        number.classList.toggle('is-error', index + 1 === errorLine);
        return number;
      }));
      syncScroll();
    }

    function input() {
      errorLine = 0;
      textarea.removeAttribute('aria-invalid');
      clearTimeout(timer);
      // Keep native text visible until the colored layer matches the new value.
      shell.classList.remove('has-highlighting');
      timer = setTimeout(render, 80);
    }

    textarea.addEventListener('input', input);
    textarea.addEventListener('scroll', syncScroll);
    const resize = new ResizeObserver(syncScroll);
    resize.observe(textarea);
    render();
    return {
      setError(line) {
        const count = textarea.value.split('\n').length;
        errorLine = Number.isInteger(Number(line)) && Number(line) > 0
          ? Math.min(Number(line), count) : 0;
        textarea.setAttribute('aria-invalid', 'true');
        clearTimeout(timer);
        render();
        if (errorLine) {
          const lines = textarea.value.split('\n');
          const start = lines.slice(0, errorLine - 1).reduce((total, text) => total + text.length + 1, 0);
          textarea.focus({preventScroll: true});
          textarea.setSelectionRange(start, start + lines[errorLine - 1].length);
          textarea.scrollTop = Math.max(0, (errorLine - 3) * parseFloat(getComputedStyle(textarea).lineHeight));
          syncScroll();
        }
      },
      destroy() {
        clearTimeout(timer);
        resize.disconnect();
        textarea.removeEventListener('input', input);
        textarea.removeEventListener('scroll', syncScroll);
      },
    };
  }

  window.BBUI.components.bashEditor = {create};
})();

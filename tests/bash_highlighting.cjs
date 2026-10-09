const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('ui/vendor/prism/prism-core.min.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('ui/vendor/prism/prism-bash.min.js', 'utf8'), context);

// Real Bash grammar: preserve source and escape markup that an admin may paste.
for (const source of [
  '#!/bin/bash\n# Comment\nif [ "$BBUI_JOB_RESULT" = "success" ]; then\n\tprintf "%s\\n" "Grüße"\nfi\n',
  'cat <<\'EOF\'\n<img src=x onerror=alert(1)>\n</script><script>alert(2)</script>\nEOF\n',
  'echo "${HOME:-/root}"; x=$(printf "%s" "$?")\n',
]) {
  const html = context.Prism.highlight(source, context.Prism.languages.bash, 'bash');
  assert.match(html, /class="token /);
  assert.doesNotMatch(html, /<(?:img|script)\b/i);
  const decoded = html.replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&amp;/g, '&');
  assert.equal(decoded, source);
}
console.log('Bash highlighting preserves source and escapes pasted markup.');

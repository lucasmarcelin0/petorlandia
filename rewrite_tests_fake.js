const fs = require('fs');
let code = fs.readFileSync('tests/test_form_feedback_contract.js', 'utf8');

if (!code.includes('closest(selector) { return this.parentNode; }')) {
    code = code.replace('closest(selector) { return null; }', 'closest(selector) { return this.parentNode || null; }');
}

fs.writeFileSync('tests/test_form_feedback_contract.js', code);

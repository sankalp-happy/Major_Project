const fs = require('fs');
const data = JSON.parse(fs.readFileSync('artifacts/phase1/sdg_v1.json'));
const calls = data.edges.filter(e => e.edge_type === 'calls');
console.log(calls.slice(0, 5).map(e => `${e.source} -> ${e.target}`));

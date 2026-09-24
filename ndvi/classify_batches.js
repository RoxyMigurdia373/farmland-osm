/* Classify downloaded GEE batches with the exact browser algorithm, bounded memory. */
const fs = require('node:fs');
const N = require('./core.js');

function classifyBatch(text, cutoff) {
  const parsed = N.parse(text), end = N.date(cutoff);
  if (!Number.isFinite(end)) throw Error('Invalid exclusive cutoff date');
  if (parsed.invalid) throw Error(`Invalid date/ID rows: ${parsed.invalid}`);
  return parsed.groups.map(group => {
    const dates = new Set();
    for (const p of group.raw) {
      if (p.t >= end) throw Error('Observation exceeds fixed cutoff');
      if (dates.has(p.t)) throw Error(`Duplicate date: ${group.id}`);
      dates.add(p.t);
    }
    const prepared = N.preprocess(group, N.defaults);
    const code = prepared ? N.classify(prepared, N.defaults) : 5;
    const valid = group.raw.filter(p => p.v !== null).sort((a,b) => a.t-b.t);
    const provisional = end < Date.UTC(group.year+1,0,1);
    const r = prepared || {};
    return {
      plot_id: group.id, year: group.year,
      ndviMax: r.ndviMax ?? null, ndviAmp: r.ndviAmp ?? null,
      ndviMeanGs: r.ndviMeanGs ?? null, peakDoy: r.peakDoy ?? null,
      className: N.names[code-1], classCode: code,
      valid_obs: valid.length, total_obs: group.raw.length,
      first_obs: valid.length ? new Date(valid[0].t).toISOString().slice(0,10) : '',
      last_obs: valid.length ? new Date(valid.at(-1).t).toISOString().slice(0,10) : '',
      provisional, end_exclusive: cutoff,
      review: provisional || code !== 1,
      reason: !prepared ? '无有效观测' : code===5 ? '有效观测不足或生长季缺数据' : 'NDVI物候阈值初筛，未经样本校准',
    };
  });
}

if (require.main === module) {
  const [manifestFile, outputFile] = process.argv.slice(2);
  if (!manifestFile || !outputFile) throw Error('Usage: node classify_batches.js manifest.json results.csv');
  const manifest = JSON.parse(fs.readFileSync(manifestFile,'utf8'));
  const seen = new Set(); let count = 0, headers;
  const temporary = outputFile + '.tmp';
  fs.writeFileSync(temporary, '\ufeff');
  const encode = v => '"' + String(v ?? '').replaceAll('"','""') + '"';
  try {
    for (const batch of manifest.batches) {
      const rows = classifyBatch(fs.readFileSync(batch.path,'utf8'), batch.end_exclusive);
      for (const r of rows) {
        const key = JSON.stringify([r.plot_id,r.year]);
        if (seen.has(key)) throw Error(`Overlapping batches: ${key}`);
        seen.add(key);
      }
      if (!rows.length) throw Error(`Empty batch: ${batch.path}`);
      if (!headers) {headers=Object.keys(rows[0]); fs.appendFileSync(temporary,headers.join(',')+'\r\n');}
      fs.appendFileSync(temporary, rows.map(r=>headers.map(k=>encode(r[k])).join(',')).join('\r\n')+'\r\n');
      count += rows.length;
    }
    fs.renameSync(temporary,outputFile);
    console.log(JSON.stringify({classified_plot_years:count,output:outputFile}));
  } catch (error) {fs.unlinkSync(temporary); throw error;}
}
module.exports = {classifyBatch};

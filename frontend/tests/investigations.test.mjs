import { test } from 'node:test';
import assert from 'node:assert/strict';
import { exportNotebook, importNotebook, loadNotebook, newFinding, newInvestigation, fromDetection, STORAGE_KEY } from '../src/investigations/model.ts';

test('GeoJSON round trip preserves geometry, review, notes and measurement provenance', () => {
  const g = newInvestigation();
  const item = newFinding({type:'LineString', coordinates:[[-80,40],[-79.999,40]]}, {revision:'original'});
  item.notes = 'Possible road'; item.evidence = 'Historical sheet 4'; item.review = 'uncertain';
  item.measurement = {method:'WGS84',revision:'data-v1',length_m:85,area_m2:null,samples:[{distance_m:0,lon:-80,lat:40,elevation_m:null,source:null}],sources:[]};
  g.findings.push(item);
  const book = {version:1,investigations:[g]};
  const imported = importNotebook(JSON.stringify(exportNotebook(book)));
  assert.equal(imported.investigations[0].findings[0].notes, item.notes);
  assert.deepEqual(imported.investigations[0].findings[0].geometry,item.geometry);
  assert.deepEqual(imported.investigations[0].findings[0].measurement,item.measurement);
});

test('invalid geometry, versions, duplicate IDs, malformed measurements rejected', () => {
  const g = newInvestigation();g.findings.push(newFinding({type:'Point',coordinates:[-80,40]},{}));
  for(const corrupt of [d=>d.investigation_version=2,d=>d.features[0].geometry.coordinates=[400,40],d=>d.features.push(d.features[0]),d=>d.features[0].properties.measurement={samples:'bad'}]) {
    const data=exportNotebook({version:1,investigations:[g]});corrupt(data);
    assert.throws(()=>importNotebook(JSON.stringify(data)));
  }
});

test('migrates legacy snapshots and preserves unreadable stored copy', () => {
  const data = new Map([['landscape-saved',JSON.stringify([{id:'a',lon:-80,lat:40,feature_type:'depression',confidence:.6}])]]);
  globalThis.localStorage={getItem:key=>data.get(key)??null};
  assert.equal(loadNotebook().book.investigations[0].findings[0].detection.id,'a');
  data.set(STORAGE_KEY,'broken');
  assert.match(loadNotebook().error,/preserved/);
  assert.equal(data.get(STORAGE_KEY),'broken');
});

test('saved suggestions contain job and algorithm provenance', () => {
  const d={id:'candidate',lon:-80,lat:40,feature_type:'depression',confidence:.7,source_passes:{job_id:'scan',pass_config:'sinkhole_survey'}};
  const finding=fromDetection(d);
  assert.equal(finding.context.job_id,'scan');
  assert.deepEqual(finding.detection,d);
  assert.equal(finding.review,'unreviewed');
});

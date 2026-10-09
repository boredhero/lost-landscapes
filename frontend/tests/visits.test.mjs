import { test } from 'node:test';
import assert from 'node:assert/strict';
import { visitIdentifiers } from '../src/analytics/visits.ts';
import { randomUUID } from 'node:crypto';
const storage = () => { const map = new Map(); return { getItem: k => map.get(k) ?? null, setItem: (k,v) => map.set(k,v) }; };

test('reload deduplicates; another tab shares browser but has a new visit', () => {
 const local = storage(), session = storage(), now = Date.now();
 const first = visitIdentifiers(local, session, now, randomUUID);
 assert.deepEqual(visitIdentifiers(local, session, now, randomUUID), first);
 const other = visitIdentifiers(local, storage(), now, randomUUID);
 assert.equal(other.browser_id, first.browser_id);
 assert.notEqual(other.visit_id, first.visit_id);
});
test('daily visit rotates and browser identity expires after 30 days', () => {
 const local = storage(), session = storage(), now = Date.now();
 const first = visitIdentifiers(local, session, now, randomUUID);
 const tomorrow = visitIdentifiers(local, session, now + 86400000, randomUUID);
 assert.equal(tomorrow.browser_id, first.browser_id);
 assert.notEqual(tomorrow.visit_id, first.visit_id);
 assert.notEqual(visitIdentifiers(local, session, now + 31 * 86400000, randomUUID).browser_id, first.browser_id);
});
test('corrupt storage recovers and blocked storage skips rather than fabricating persistence', () => {
 const local = storage(), session = storage();
 local.setItem('landscape-visitor-v1', '{bad');
 assert.ok(visitIdentifiers(local, session, Date.now(), randomUUID).browser_id);
 assert.throws(() => visitIdentifiers({getItem(){throw Error('blocked')}}, session, Date.now(), randomUUID));
});

test('privacy signals skip sending and request failures stay isolated', async () => {
 const { recordVisit } = await import('../src/analytics/visits.ts');
 const originals = Object.fromEntries(['navigator', 'localStorage', 'sessionStorage', 'fetch'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
 let calls = 0;
 const install = (k, value) => Object.defineProperty(globalThis, k, {value, configurable:true});
 try {
  install('localStorage', storage()); install('sessionStorage', storage());
  install('fetch', () => { calls++; return Promise.reject(new Error('offline')); });
  install('navigator', {doNotTrack:'1'}); recordVisit();
  install('navigator', {globalPrivacyControl:true}); recordVisit();
  assert.equal(calls, 0);
  install('navigator', {}); recordVisit();
  await Promise.resolve();
  assert.equal(calls, 1);
 } finally {
  for(const [key, descriptor] of Object.entries(originals)) {
   if(descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
  }
 }
});

import { describe, it, expect } from 'vitest';
import { globMatch } from './glob-match.js';

describe('globMatch', () => {
  it('matches exact paths', () => {
    expect(globMatch('src/lib/events.js', 'src/lib/events.js')).toBe(true);
  });
  it('rejects non-matching exact paths', () => {
    expect(globMatch('src/lib/events.js', 'src/lib/layout.js')).toBe(false);
  });
  it('matches * as single segment wildcard', () => {
    expect(globMatch('src/lib/*.js', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/lib/*.js', 'src/lib/deep/events.js')).toBe(false);
  });
  it('matches ** as multi-segment wildcard', () => {
    expect(globMatch('src/**/*.js', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/**/*.js', 'src/lib/deep/events.js')).toBe(true);
    expect(globMatch('src/**/*.js', 'other/file.js')).toBe(false);
  });
  it('matches ? as single character', () => {
    expect(globMatch('src/lib/events.?s', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/lib/events.?s', 'src/lib/events.ts')).toBe(true);
    expect(globMatch('src/lib/events.?s', 'src/lib/events.css')).toBe(false);
  });
  it('matches src/lib/events.* pattern', () => {
    expect(globMatch('src/lib/events.*', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/lib/events.*', 'src/lib/events.test.js')).toBe(false);
  });
  it('normalizes backslashes to forward slashes', () => {
    expect(globMatch('src/lib/*.js', 'src\\lib\\events.js')).toBe(true);
  });
});

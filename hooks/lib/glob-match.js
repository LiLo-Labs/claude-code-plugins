/**
 * Minimal glob matcher — zero dependencies, no dynamic RegExp.
 * Supports: * (single segment), ** (multi-segment), ? (single char)
 */
export function globMatch(pattern, filePath) {
  const p = pattern.replace(/\\/g, '/');
  const f = filePath.replace(/\\/g, '/');
  return matchSegments(p.split('/'), f.split('/'), 0, 0);
}

/**
 * Recursive segment-by-segment matcher.
 * @param {string[]} ps - pattern segments
 * @param {string[]} fs - file path segments
 * @param {number} pi  - current index into ps
 * @param {number} fi  - current index into fs
 * @returns {boolean}
 */
function matchSegments(ps, fs, pi, fi) {
  // Consumed all pattern segments — match iff all file segments consumed too
  if (pi === ps.length) return fi === fs.length;

  const seg = ps[pi];

  if (seg === '**') {
    // ** can consume zero or more file segments
    for (let skip = fi; skip <= fs.length; skip++) {
      if (matchSegments(ps, fs, pi + 1, skip)) return true;
    }
    return false;
  }

  // Need a file segment to match against
  if (fi === fs.length) return false;

  if (matchGlob(seg, fs[fi])) {
    return matchSegments(ps, fs, pi + 1, fi + 1);
  }
  return false;
}

/**
 * Match a single glob segment (no path separators) against a file segment.
 * Supports * (matches any chars except '.') and ? (matches one char except '.').
 * This mirrors shell glob semantics where * does not cross dot boundaries
 * within a filename segment (e.g. events.* matches events.js but not
 * events.test.js).
 * @param {string} pattern
 * @param {string} str
 * @returns {boolean}
 */
function matchGlob(pattern, str) {
  // dp[i][j] = pattern[0..i) matches str[0..j)
  const m = pattern.length;
  const n = str.length;
  // Use two rows to keep memory O(n)
  let prev = new Array(n + 1).fill(false);
  prev[0] = true;

  for (let i = 1; i <= m; i++) {
    const curr = new Array(n + 1).fill(false);
    const ch = pattern[i - 1];
    if (ch === '*') {
      // * matches empty string
      curr[0] = prev[0];
    }
    for (let j = 1; j <= n; j++) {
      const sc = str[j - 1];
      if (ch === '*') {
        // * can match zero chars (prev[j]) but cannot consume a '.' char
        if (sc === '.') {
          curr[j] = prev[j];  // zero-length match allowed; consuming '.' is not
        } else {
          curr[j] = curr[j - 1] || prev[j];
        }
      } else if (ch === '?') {
        curr[j] = prev[j - 1] && sc !== '.';
      } else {
        curr[j] = prev[j - 1] && ch === sc;
      }
    }
    prev = curr;
  }

  return prev[n];
}
